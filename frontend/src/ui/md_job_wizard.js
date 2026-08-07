/**
 * md_job_wizard.js — the NAMD Job Wizard modal.
 *
 * The problem it solves: what a NAMD run actually does was spread across four layers that
 * never appeared together — a request field's default, the preset merged over it, a
 * server-side override that discarded both, and a per-stage derivation inside the conf
 * writer. The panel's flat "Advanced" grid showed none of that, so the number on screen
 * was frequently not the number that ran, and the 22-stage ladder was invisible entirely.
 *
 * So this view shows every stage as a column, every parameter as a row, highlights what
 * changes from one stage to the next, and states every condition that can skip, alter or
 * repeat a stage. Nothing here is hand-written: `POST /md/protocol-plan` builds the whole
 * table by running the real NAMD conf writers, and re-runs on every edit.
 *
 * Boundary: the wizard owns PROTOCOL parameters. The panel keeps owning ENVIRONMENT —
 * anchors, electric field, run directory, cluster target — and every launch gate (VRAM
 * pre-flight, disk forecast, concurrency confirms). The wizard hands the panel a payload;
 * the panel runs the gates it already runs.
 */
import { createButton, createInput, createSelect, createModal, el } from './primitives/index.js'
import { initWizardTargetStep } from './md_job_wizard_target.js'
import { renderSlurmDetails } from './md_job_wizard_target_model.js'
import {
  allStageConditions,
  applySnapshot,
  blockingConditions,
  conditionBadges,
  conditionsByField,
  conditionsByStage,
  conditionTooltip,
  fieldAlert,
  fieldScope,
  deferredNotes,
  inheritedRows,
  makeDebounce,
  paramLabel,
  paramRows,
  presetSummary,
  productionColumns,
  productionField,
  productionPayload,
  planPayload,
  pushUndo,
  productionParents,
  clearStageOverrides,
  normaliseOverrideInput,
  overrideSummary,
  setStageOverride,
  snapshotState,
  stageColumns,
  wizardPayload,
} from './md_job_wizard_model.js'

const PLAN_DEBOUNCE_MS = 250

/** How many changes back undo reaches. Deep enough that a session of tuning is safe,
 *  shallow enough that the stack never becomes a memory question. */
const UNDO_LIMIT = 50

/** The two halves of the wizard. Setting up a run and reading what that run will do are
 *  different tasks — every setting on one screen, the resulting 22-stage ladder and its
 *  conditions on the next — so neither has to be squeezed into a column. */
const TABS = [
  ['target', 'Where it runs'],
  ['setup', 'Protocol & settings'],
  ['plan', 'What each stage runs'],
]

/** The one wizard setting that is a standing PREFERENCE rather than a per-run choice:
 *  whether an unattended run should pause and ask when the fastest GPU mode cannot
 *  start, or quietly accept the ~3x slower path. Answering it every time would be a
 *  nuisance, and forgetting it silently changes how a run behaves overnight. */
const GPU_FALLBACK_KEY = 'nadoc:md-jobs-gpu-fallback'

/** The protocol tiers that answer the question a run actually turns on — are you
 *  reproducing the literature, or getting an answer about your design? The rest stay
 *  available under a disclosure rather than being hidden. */
const HEADLINE_PRESETS = ['literature', 'design_speed']

/** Rows with no per-stage meaning — the backend refuses them and the table renders them
 *  read-only, so they get no set-for-every-stage affordance either. */
const PROTECTED_ROWS = new Set([
  'structure', 'coordinates', 'outputname', 'dcdfile', 'xstfile', 'veldcdfile',
  'forcedcdfile', 'bincoordinates', 'binvelocities', 'extendedsystem', 'parameters',
  'paratypecharmm',
])

/**
 * Every parameter the wizard exposes, with the control to render it. This list IS the
 * "no hidden parameters" promise — anything a job request carries and a user can
 * meaningfully choose belongs here.
 */
const FIELDS = [
  { key: 'padding_nm', label: 'Water padding', unit: 'nm', type: 'number', step: 0.1, min: 0.1,
    help: 'Water added on every face of the solute. The reference protocol uses 2.0 nm (its bounding box ± 20 Å). Trimmed automatically if the resulting cell will not fit this machine.' },
  { key: 'water_shell_nm', label: 'Water shell carve', unit: 'nm', type: 'number', step: 0.1, min: 0,
    help: '0 = a full water box. A value here keeps only water within that distance of the DNA, which halves the atom count — but leaves vacuum in the cell, so the run must go to constant volume. That removes the settle stage AND the box-size equilibration criterion.' },
  { key: 'production_ns_intent', label: 'Intended production length', unit: 'ns', type: 'number', step: 1, min: 0,
    help: 'THE cell-sizing decision, and the only place it can be made. Above 20 ns the box is sized so the structure can turn through any orientation without meeting its periodic image; below it, the cheaper bounding-box cell is used. Nothing after preparation re-solvates, and a production run inherits this cell verbatim.' },
  { key: 'salt_mode', label: 'Ionic conditions', type: 'select',
    options: [{ value: 'screening', label: 'Screening (validated origami defaults)' },
              { value: 'custom', label: 'Custom' }],
    help: 'Screening pins magnesium to 12.5 mM with no sodium, and the origami is neutralised by Mg(H₂O)₆ — the published condition. Custom hands the two fields below back to you.' },
  { key: 'mg_conc_mM', label: 'Magnesium', unit: 'mM', type: 'number', step: 0.5, min: 0 },
  { key: 'ion_conc_mM', label: 'NaCl', unit: 'mM', type: 'number', step: 5, min: 0 },
  { key: 'minimize_steps', label: 'Minimisation steps', type: 'number', step: 100, min: 100,
    help: 'A FLOOR, not the value: minimisation scales to one step per 10 atoms after solvation. A flat count is safe on a small bundle and catastrophic on a large origami.' },
  // ── The three integrator axes, separated (exp51, 2026-08-05) ──
  // These used to be one dial: "Fast relaxation (HMR + 4 fs)" bundled a timestep with a
  // mass set, and rigidBonds was never exposed at all. exp51 measured the combinations
  // the old code could not emit; each axis is now its own control, with the measurement
  // stated as a condition whenever a combination is unsound.
  { key: 'relax_timestep_fs', label: 'Ladder timestep', unit: 'fs', type: 'select',
    options: [{ value: '4', label: '4 fs (faster, risks RATTLE)' },
              { value: '2', label: '2 fs (standard)' },
              { value: '1', label: '1 fs (conservative)' }],
    parse: Number,
    fallback: plan => (plan?.request?.fast?.value ? 4 : 2),
    help: 'The base timestep for the relaxation ladder — NOT for production, which has its own below. Per-stage tiers still apply on top: a stage that needs the soft integrator runs 1 fs and a declashed ladder runs 2 fs whatever this says, and the stage table shows exactly what each column will use.' },
  { key: 'relax_rigid_bonds', label: 'Ladder rigid bonds', type: 'checkbox',
    // The box shows what the run WILL do: ticked = rigidBonds all. Untouched it follows
    // the timestep's recommendation; touching it makes the choice explicit, and any
    // mismatch with the timestep raises its own warning against this control.
    fallback: (plan, valueOf) => (Number(valueOf('relax_timestep_fs')) <= 1 ? 'none' : 'all'),
    check: v => v === 'all',
    parse: on => (on ? 'all' : 'none'),
    help: 'Hold bonds to hydrogen rigid (RATTLE). Constraining them removes the ~11 fs X–H stretch, which is what makes 2 fs possible at all. Recommended on above 1 fs; exp51 measured 1 fs + rigid to be perfectly stable too, so it is a free choice there.' },
  { key: 'relax_hmr', label: 'Ladder H-mass repartitioning (HMR)', type: 'checkbox',
    fallback: (plan, valueOf) => Number(valueOf('relax_timestep_fs')) >= 4,
    check: v => !!v,
    parse: on => !!on,
    help: 'Move mass from each non-water hydrogen onto its bonded heavy atom (×3), slowing the X–H stretch so a 4 fs step is stable. Recommended on at 4 fs and off below: exp51 measured 4 fs on standard masses failing RATTLE after 16.8 ps, and HMR below 4 fs costing 3.5–35× in energy conservation.' },
  { key: 'early_stop_relax', label: 'Stop settled stages early', type: 'checkbox',
    help: 'Skip a stage’s remaining chunks once BOTH its energy and its base pairing are flat. Turn it off for a run whose numbers are going in a paper.' },
  { key: 'production_timestep_fs', label: 'Timestep', unit: 'fs', type: 'select',
    options: [{ value: '4', label: '4 fs (faster, risks RATTLE)' },
              { value: '2', label: '2 fs (standard)' },
              { value: '1', label: '1 fs (conservative)' }],
    parse: Number,
    help: 'The PRODUCTION run’s integrator — recorded now, used when you run production off this package; the relaxation ladder runs at its own timestep and never constrains this. Only these three are allowed — 2.5/3/3.5 fs are refused outright.' },
  { key: 'production_rigid_bonds', label: 'Production rigid bonds', type: 'checkbox',
    fallback: (plan, valueOf) => (Number(valueOf('production_timestep_fs')) <= 1 ? 'none' : 'all'),
    check: v => v === 'all',
    parse: on => (on ? 'all' : 'none'),
    help: 'The same axis as the ladder’s, for the production run.' },
  { key: 'production_hmr', label: 'Production H-mass repartitioning (HMR)', type: 'checkbox',
    fallback: (plan, valueOf) => Number(valueOf('production_timestep_fs')) >= 4,
    check: v => !!v,
    parse: on => !!on,
    help: 'The repartitioned PSF is built on demand, so production does not need the ladder to have run with HMR.' },
  { key: 'allow_water_shell_carve', label: 'Allow a carve if the full box will not fit', type: 'checkbox',
    help: 'Off means the job STOPS rather than shrinking the water, because a carve stops the run being the published protocol.' },
  { key: 'gpu_resident', label: 'GPU-resident mode', type: 'select',
    options: [{ value: 'auto', label: 'Auto (decide from the atom count)' },
              { value: 'on', label: 'On' }, { value: 'off', label: 'Off' }],
    help: 'Keeps integration and bonded forces on the GPU. A large win above ~100k atoms and a measured loss below it, so auto is usually right.' },
  { key: 'gpu_fallback_policy', label: 'If the fastest GPU mode cannot start', type: 'select',
    options: [{ value: 'ask', label: 'Pause and ask' },
              { value: 'auto_offload', label: 'Fall back automatically' }],
    help: 'Pausing means an unattended run stops and notifies instead of silently running about three times slower.' },
  { key: 'threads', label: 'CPU threads', type: 'number', step: 1, min: 1 },
  { key: 'devices', label: 'CUDA devices', type: 'text',
    help: '"0" for the first GPU, "0,1" for two, or "cpu" for the multicore build.' },
]

/**
 * Every parameter a PRODUCTION run exposes, in the same descriptor shape as `FIELDS`.
 *
 * Production used to render a hand-written half-dozen controls with no provenance chip,
 * no condition reference and no warning icon, and with three of its settings missing
 * outright — GPU-resident was sent from a control that was never drawn, so it could only
 * ever be the package's default, and the two integrator axes the ladder exposes had no
 * production counterpart at all. These go through `renderField` exactly as the relaxation
 * ones do, so everything the wizard promises about a setting is true of these too.
 *
 * Keys are the wizard's own state names. `production_*` and `gpu_resident` deliberately
 * match the create-request field names, because the plan reports them under those names
 * and the condition sources point at them; `productionPayload` renames the two integrator
 * axes on the way out (see its comment).
 */
const PRODUCTION_FIELD_DEFS = [
  { key: 'length_ns', label: 'Run length', unit: 'ns', type: 'number', step: 1, min: 0.001,
    group: 'run',
    help: 'How long the unrestrained run samples for. The cell was sized once, when the relaxation was prepared — a run longer than that cell supports is flagged as a condition on the next tab, with the override.' },
  { key: 'dcd_freq', label: 'Trajectory interval', unit: 'steps', type: 'number', step: 100, min: 100,
    group: 'run',
    help: 'How often a frame is written. Larger means a smaller file: the disk forecast scales directly with this. Lower it when the trajectory feeds fluctuation-based parameter extraction (FEM/SNUPI/mrDNA).' },
  { key: 'enm_restraints', label: 'Restraints', type: 'select', group: 'run',
    options: [{ value: 'auto', label: 'Follow the parent’s protocol' },
              { value: 'on', label: 'Keep an elastic network (as the published runs do)' },
              { value: 'off', label: 'None — genuinely unrestrained' }],
    format: v => (v == null ? 'auto' : String(v)),
    help: 'The published “unrestrained” origami productions retain a network at k = 0.1 kcal/mol/Å² throughout. Sampling a template-built structure with none at all gives a softer ensemble — more breathing, more fraying, larger RMSD drift. The network is rebuilt from the equilibrated coordinates this run starts from, never from the pre-relaxation build.' },
  { key: 'langevin_damping', label: 'Langevin coupling', unit: 'ps⁻¹', type: 'number',
    step: 0.5, min: 0.01, group: 'run',
    help: 'Blank uses the literature production value (1). The ladder runs at 5, which is an equilibration setting: at that coupling the dynamics are overdamped, so anything time-dependent — diffusion, relaxation times, breathing kinetics — is scaled by something unrelated to the system. Equilibrium averages are unaffected.' },
  { key: 'seed', label: 'Random seed', type: 'number', step: 1, min: 1, group: 'run',
    help: ({ continuation }) => (continuation
      ? 'Blank draws a fresh seed when the job is created. This run inherits its velocities from the checkpoint it continues, so the seed does not choose them — it drives the Langevin thermostat from that point on. Two continuations of one checkpoint with different seeds diverge, but both carry the parent’s whole history, so they are not independent samples of it.'
      : 'Blank draws a fresh seed when the job is created, which is what makes several productions off one relaxation independent samples. Set one only to reproduce a specific past trajectory — the seed a run used is recorded on the job and in its manifest.') },
  { key: 'production_timestep_fs', label: 'Timestep', unit: 'fs', type: 'select',
    group: 'integrator',
    options: [{ value: '4', label: '4 fs (faster, risks RATTLE)' },
              { value: '2', label: '2 fs (standard)' },
              { value: '1', label: '1 fs (conservative)' }],
    parse: Number,
    help: ({ continuation }) => 'The relaxation does not constrain this — a ladder exists to hand over equilibrated coordinates, and once it has, production may run at any sanctioned timestep. Each option changes more than the number: 4 fs is rigid bonds on a repartitioned PSF, 2 fs is rigid bonds on standard masses, 1 fs is flexible. Only these three are allowed.'
      + (continuation
        ? ' Changing it mid-chain is legal but makes a discontinuity: the two legs are then not one trajectory at one integrator, which matters for anything read off the combined run.'
        : '') },
  { key: 'production_rigid_bonds', label: 'Rigid bonds', type: 'checkbox',
    group: 'integrator',
    fallback: (plan, valueOf) => (Number(valueOf('production_timestep_fs')) <= 1 ? 'none' : 'all'),
    check: v => v === 'all',
    parse: on => (on ? 'all' : 'none'),
    help: 'Hold bonds to hydrogen rigid (RATTLE). Constraining them removes the ~11 fs X–H stretch, which is what makes 2 fs possible at all. Recommended on above 1 fs; exp51 measured 1 fs + rigid to be perfectly stable too, so it is a free choice there.' },
  { key: 'production_hmr', label: 'H-mass repartitioning (HMR)', type: 'checkbox',
    group: 'integrator',
    fallback: (plan, valueOf) => Number(valueOf('production_timestep_fs')) >= 4,
    check: v => !!v,
    parse: on => !!on,
    help: 'Move mass from each non-water hydrogen onto its bonded heavy atom (×3), slowing the X–H stretch so a 4 fs step is stable. The repartitioned PSF is built on demand from the package’s own topology, so this run may use HMR even if the relaxation did not.' },
  { key: 'gpu_resident', label: 'GPU-resident mode', type: 'select', group: 'integrator',
    options: [{ value: 'auto', label: 'Auto (decide from the atom count)' },
              { value: 'on', label: 'On' }, { value: 'off', label: 'Off' }],
    format: v => (v == null ? 'auto' : String(v)),
    help: 'Keeps integration and bonded forces on the GPU. The atom count is known here (it is the package’s own PSF), so auto resolves to a fact rather than a deferred value. A hard anchor forces this off — NAMD 3 refuses fixedAtoms under GPU-resident.' },
]

/** The production pane's groups, in order. */
const PRODUCTION_GROUPS = [
  { key: 'run', title: 'This production run',
    help: 'What this run samples, for how long, and under what restraints. None of it is inherited — each is a choice about this trajectory.' },
  { key: 'integrator', title: 'Integrator and hardware',
    help: 'Recorded on the package when the relaxation was prepared, and overridable here for this run alone. An untouched control shows what the package’s own choice resolves to.' },
]

/** The settings pane's groups, in order. Every control states which run it governs —
 *  the flat list could not, and that is how a production-only field ended up looking
 *  like a relaxation setting. */
const SCOPE_GROUPS = [
  { scope: 'relaxation', title: 'Relaxation ladder',
    help: 'Applies to the 22-stage relaxation this job runs now — the stage table on the next tab is exactly these settings.' },
  { scope: 'production', title: 'Production run',
    help: 'Recorded now, applied when you later run production off this package. Changing these does not alter the ladder.' },
  { scope: 'both', title: 'Both runs',
    help: 'Solvation, chemistry and hardware. The cell and the PSF the relaxation builds are what production inherits, so these are shared by construction.' },
]

const PROVENANCE_TEXT = {
  user: 'you set this',
  preset: 'from the protocol',
  default: 'default',
  forced: 'forced by the server',
  derived: 'derived',
  // Production only: chosen when the relaxation package was prepared. Distinct from
  // "default" because a default is what nobody chose, and this is what somebody chose
  // for the run being continued.
  inherited: 'from the relaxation',
}

/**
 * @param {object} deps
 * @param {object} deps.api                 { getRelaxPresets, fetchProtocolPlan, listSimJobs }
 * @param {(payload:object)=>Promise<any>} deps.launch          runs the panel's gate sequence
 * @param {(parentId:string, body:object)=>Promise<any>} deps.spawnProduction
 * @param {()=>Array} deps.getJobs          the panel's cached job list
 * @param {()=>string|null} deps.getPartPath
 * @param {(jobId:string)=>void} [deps.onJobCreated]
 * @param {(mount:{button:HTMLElement, progressEl:HTMLElement})=>void} [deps.onOptimizeMount]
 *        Called once, when the modal is first built, with the ⚡ "Optimize for this
 *        machine" button and its progress host. The recommender lives in the panel (it
 *        needs the API client and the design), but its CONTROLS belong here now that this
 *        is where settings are.
 */
export function initJobWizard({ api, launch, spawnProduction, getJobs, getPartPath,
  onJobCreated, onOptimizeMount, onTargetChange = () => {} } = {}) {
  let modal = null
  let presets = []
  let plan = null
  let busy = false

  const state = {
    mode: 'relaxation',
    // Which step is showing. Not undoable — moving between tabs changes nothing about
    // the run.
    tab: 'target',
    // Step 1's answer. WHERE a job runs is a property of the run, so unlike `tab` it is
    // undoable and it rides along in the payload.
    target: 'local',
    partition: null,
    presetId: 'design_speed',
    touched: {},          // only what the user actually changed — see wizardPayload
    // Set when the wizard was opened for a SEEDED DRAFT: submitting then solvates that
    // job in place (from its source engine's coordinates) instead of creating a new one.
    draftId: null,
    parentJobId: null,
    // {stageIndex|'*': {directive: value}} — hand edits to individual stages. Sent with
    // the job, applied to the emitted confs, and declared in the package's own fidelity
    // block, because a hand edit is a departure from every protocol by definition.
    stageOverrides: {},
  }

  // Mounts, so a re-render replaces content instead of rebuilding the modal.
  const mounts = {
    preset: el('div', { className: 'wizard-presets' }),
    fields: el('div', { className: 'wizard-fields' }),
    stages: el('div', { className: 'wizard-stages' }),
    conditions: el('div', { className: 'wizard-conditions' }),
    summary: el('div', { className: 'wizard-summary' }),
    source: el('div', { className: 'wizard-source' }),
    status: el('div', { className: 'wizard-status' }),
    // Only filled for a cluster target — a local run has no SLURM request to inspect.
    slurm: el('div', { className: 'wizard-slurm' }),
  }

  const refetch = makeDebounce(() => { void loadPlan() }, PLAN_DEBOUNCE_MS)

  // ── Undo ────────────────────────────────────────────────────────────────────
  /** Snapshots of the state BEFORE each change, newest last.
   *
   *  Every value in this wizard is typed into a control that then re-plans, and several
   *  of them (a stage cell, a set-for-every-stage sweep, ⚡) are destructive enough that
   *  "what was it before?" has no answer once the plan comes back. One stack covers all
   *  of them uniformly — settings fields, stage-table cells, protocol and mode. */
  let undoStack = []
  let undoBtn = null

  /** Call at the top of any handler that is about to change the state. */
  function record() {
    undoStack = pushUndo(undoStack, snapshotState(state), UNDO_LIMIT)
    paintUndo()
  }

  function undo() {
    const snap = undoStack[undoStack.length - 1]
    if (!snap) return
    undoStack = undoStack.slice(0, -1)
    applySnapshot(state, snap)
    paintUndo()
    renderSource()
    render()
    void loadPlan()
  }

  function paintUndo() {
    if (!undoBtn) return
    undoBtn.disabled = !undoStack.length
    undoBtn.title = undoStack.length
      ? `Undo the last change (${undoStack.length} to go back through) — Ctrl+Z`
      : 'Nothing to undo yet'
  }

  // ── Plan ────────────────────────────────────────────────────────────────────
  /** Default the production parent to the newest completed relaxation for this part.
   *  Resolved BEFORE the plan request rather than while rendering the picker, or the
   *  first plan would fire with no parent and the table would come back empty. */
  function ensureParent() {
    if (state.mode !== 'production') return
    const choices = productionParents(getJobs?.() || [], getPartPath?.(),
                                      { includeJobId: state.parentJobId })
    if (!choices.length) { state.parentJobId = null; return }
    if (!state.parentJobId || !choices.some(c => c.job.job_id === state.parentJobId)) {
      state.parentJobId = choices[0].job.job_id
    }
  }

  async function loadPlan() {
    ensureParent()
    if (state.mode === 'production' && !state.parentJobId) {
      // No relaxation to seed from — the empty state says so; a plan request would just
      // 400 and paint a scarier message over it.
      plan = null
      mounts.status.textContent = ''
      render()
      return
    }
    mounts.status.textContent = 'Working out what this will run…'
    try {
      const next = await api.fetchProtocolPlan(planPayload(state))
      plan = next || null
      // The API client returns null on a non-OK response rather than throwing, so an
      // un-surfaced failure would leave the table silently blank — which is exactly the
      // kind of "nothing happened and I don't know why" the wizard exists to end.
      mounts.status.textContent = plan
        ? ''
        : `Could not work out what this would run: ${api.lastErrorMessage?.() || 'server error'}`
    } catch (err) {
      plan = null
      mounts.status.textContent = `Could not work out what this would run: ${err?.message || err}`
    }
    render()
  }

  /** What the plan says about a field. In production mode the production-resolved block
   *  wins, because the four settings that exist in both are resolved differently there:
   *  the create-request merge reports the preset's value, while a production child
   *  inherits whatever its package recorded at prep time. */
  function planField(key) {
    return state.mode === 'production'
      ? productionField(plan, key)
      : (plan?.request?.[key] || null)
  }

  /** Is this field one the SERVER decides, whatever we send? Screening mode's ion
   *  concentrations, and any field the chosen protocol locks. A stale touched value must
   *  never win over one of these, or the control would display a lie. */
  function isForced(key) {
    return planField(key)?.provenance === 'forced'
  }

  /** The effective value of a field: what the user typed, else what the plan resolved. */
  function valueOf(key) {
    if (!isForced(key) && Object.prototype.hasOwnProperty.call(state.touched, key)) {
      return state.touched[key]
    }
    return planField(key)?.value
  }

  /** The value a field will really use: what is stored, else what its own `fallback`
   *  resolves. Fields whose default depends on a SIBLING (rigid bonds and HMR both follow
   *  the timestep) must read through this, not `valueOf` — an untouched timestep is stored
   *  as null, and Number(null) is 0, which silently read as "1 fs" and left both boxes
   *  unticked on a 4 fs ladder. */
  function effectiveValue(key) {
    const v = valueOf(key)
    if (v != null) return v
    const field = fieldDef(key)
    return field?.fallback ? field.fallback(plan, effectiveValue) : v
  }

  /** The descriptor for a field key, from whichever list this mode renders. */
  function fieldDef(key) {
    return (state.mode === 'production' ? PRODUCTION_FIELD_DEFS : FIELDS)
      .find(f => f.key === key)
  }

  function provenanceOf(key) {
    if (isForced(key)) return 'forced'
    if (Object.prototype.hasOwnProperty.call(state.touched, key)) return 'user'
    return planField(key)?.provenance || 'default'
  }

  function setField(key, value) {
    record()
    state.touched[key] = value
    if (key === 'gpu_fallback_policy') {
      try { localStorage.setItem(GPU_FALLBACK_KEY, String(value)) } catch { /* private mode */ }
    }
    refetch()
    renderFields()          // immediate feedback; the table follows when the plan lands
  }

  /** Restore the remembered GPU-fallback preference into a fresh wizard session. */
  function restorePreferences() {
    let saved = null
    try { saved = localStorage.getItem(GPU_FALLBACK_KEY) } catch { /* private mode */ }
    if (saved === 'ask' || saved === 'auto_offload') state.touched.gpu_fallback_policy = saved
  }

  // ── Presets ─────────────────────────────────────────────────────────────────
  function renderPresets() {
    mounts.preset.replaceChildren()
    // A relaxation PRESET has nothing to say about a production run: production reads its
    // chemistry, cell and ions from the package the relaxation already built. Showing the
    // cards here would offer a choice that changes nothing.
    if (state.mode === 'production') return
    const headline = presets.filter(p => HEADLINE_PRESETS.includes(p.id))
    const rest = presets.filter(p => !HEADLINE_PRESETS.includes(p.id))

    mounts.preset.appendChild(el('div', {
      className: 'wizard-preset-cards',
      children: headline.map(presetCard),
    }))
    if (rest.length) {
      mounts.preset.appendChild(el('details', {
        className: 'wizard-more-presets',
        attrs: { open: rest.some(p => p.id === state.presetId) || undefined },
        children: [
          el('summary', { text: 'Other protocols' }),
          el('div', { className: 'wizard-preset-cards', children: rest.map(presetCard) }),
        ],
      }))
    }
  }

  function presetCard(preset) {
    const chosen = preset.id === state.presetId
    const summary = presetSummary(preset, plan)
    const classes = ['wizard-preset']
    if (chosen) classes.push('is-selected')
    if (!summary.available) classes.push('is-unavailable')
    return el('button', {
      className: classes.join(' '),
      attrs: { type: 'button', disabled: summary.available ? undefined : true,
               title: summary.unavailableReason || preset.reference || '' },
      on: {
        click: () => {
          if (!summary.available || preset.id === state.presetId) return
          record()
          state.presetId = preset.id
          // Deliberately NOT clearing `touched`: a value you set by hand survives a
          // protocol change, and its chip stays "you set this" so you can see that it
          // is no longer following the protocol.
          renderPresets()
          void loadPlan()
        },
      },
      children: [
        el('div', { className: 'wizard-preset__label', text: preset.label }),
        el('div', { className: 'wizard-preset__summary', text: preset.summary }),
        preset.reference
          ? el('div', { className: 'wizard-preset__ref', text: preset.reference })
          : null,
        summary.available
          ? (chosen ? el('div', { className: 'wizard-preset__note', text: summary.note }) : null)
          : el('div', { className: 'wizard-preset__note', text: summary.unavailableReason }),
      ],
    })
  }

  // ── Parameter rows ──────────────────────────────────────────────────────────
  function renderFields() {
    mounts.fields.replaceChildren()
    if (state.mode === 'production') { renderProductionFields(); return }

    const fieldConds = conditionsByField(plan)
    // Grouped by WHICH RUN each setting governs. A flat list put the production timestep
    // between two ladder settings, so nothing on screen said which run a control changed.
    const groups = new Map(SCOPE_GROUPS.map(g => [g.scope, []]))
    for (const field of FIELDS) {
      const scope = fieldScope(field.key, plan)
      ;(groups.get(scope) || groups.get('both')).push(field)
    }
    for (const group of SCOPE_GROUPS) {
      const fields = groups.get(group.scope) || []
      if (!fields.length) continue
      // Each group is its own block with its own column flow. One flow across all three
      // would let a group's heading land in a different column from its fields, which is
      // worse than no grouping at all.
      const body = el('div', { className: 'wizard-scope__fields' })
      mounts.fields.appendChild(el('section', {
        className: `wizard-scope wizard-scope--${group.scope}`,
        children: [
          el('h4', { className: 'wizard-scope__title', text: group.title }),
          el('div', { className: 'wizard-scope__help', text: group.help }),
          body,
        ],
      }))
      for (const field of fields) renderField(field, fieldConds, body)
    }
  }

  function renderField(field, fieldConds, parent) {
    {
      const provenance = provenanceOf(field.key)
      let value = valueOf(field.key)
      // An unset field shows what the run WILL use, not a blank. `valueOf` is passed in
      // so a fallback can read a sibling control (rigid bonds and HMR both follow the
      // timestep that is selected RIGHT NOW, not the one the last plan was built with).
      if (value == null && field.fallback) value = field.fallback(plan, effectiveValue)
      const forced = provenance === 'forced'
      // Through `planField`, not `plan.request` — in production mode the four settings
      // that exist in both blocks resolve differently, and reading the create-request one
      // captioned an inherited 4 fs with the RELAXATION preset that set the ladder's.
      const reason = planField(field.key)?.reason || ''

      let control
      if (field.type === 'checkbox') {
        // `check` maps the field's own vocabulary onto the box ("all"/"none" for
        // rigidBonds); `parse` maps it back. Without them a string value would read as
        // truthy and every rigid-bond box would show ticked.
        const on = field.check ? field.check(value) : !!value
        control = el('input', {
          className: 'wizard-check',
          attrs: { type: 'checkbox', checked: on ? true : undefined,
                   disabled: forced || undefined },
          on: { change: e => setField(field.key,
            field.parse ? field.parse(e.target.checked) : e.target.checked) },
        })
      } else if (field.type === 'select') {
        // `format` exists for the tri-states: their VALUE is null/true/false but their
        // option values are ''/'on'/'off', so String(value) would select nothing.
        const shown = field.format ? field.format(value) : (value == null ? '' : String(value))
        control = createSelect({
          size: 'sm', options: field.options,
          value: shown,
          disabled: forced,
          onChange: v => setField(field.key, field.parse ? field.parse(v) : v),
        })
      } else {
        control = createInput({
          size: 'sm', type: field.type === 'number' ? 'number' : 'text',
          value: value == null ? '' : String(value),
          step: field.step, min: field.min, disabled: forced,
          onChange: v => setField(field.key,
            field.type === 'number' ? (v === '' ? null : Number(v)) : v),
        })
      }

      ;(parent || mounts.fields).appendChild(el('div', {
        className: 'wizard-field',
        children: [
          el('label', {
            className: 'wizard-field__label',
            children: [
              document.createTextNode(field.label),
              field.unit ? el('span', { className: 'wizard-field__unit', text: ` (${field.unit})` }) : null,
              alertIcon(fieldConds.get(field.key)),
              conditionRefs(fieldConds.get(field.key)),
            ],
          }),
          el('div', { className: 'wizard-field__control', children: [control] }),
          el('div', {
            className: `wizard-chip wizard-chip--${provenance}`,
            attrs: { title: reason },
            text: PROVENANCE_TEXT[provenance] || provenance,
          }),
          // The reason and the help answer different questions — "why is it THIS value"
          // and "what does this setting do" — and the reason used to REPLACE the help.
          // Harmless while most reasons were empty; once production gave every field one,
          // every production control lost its explanation to a one-line provenance note.
          reason ? el('div', { className: 'wizard-field__why', text: reason }) : null,
          field.help
            ? el('div', { className: 'wizard-field__help', text: helpText(field) })
            : null,
        ],
      }))
    }
  }

  /** A field's help, which a few settings have to word differently in a CONTINUATION —
   *  a run extending a production is not doing the same thing as one sampling off a
   *  relaxation, and the sentence that explains the seed is the clearest example. */
  function helpText(field) {
    const help = field.help
    return typeof help === 'function' ? help({ continuation: !!plan?.continuation }) : help
  }

  /** ⚠ on a control whose current value the plan objects to. The objection itself is the
   *  condition next to it — this is only what makes it visible without reading. */
  function alertIcon(conds) {
    const kind = fieldAlert(conds)
    if (!kind) return null
    return el('span', {
      className: `wizard-field__alert wizard-field__alert--${kind}`,
      attrs: { title: conds.map(conditionTooltip).join('\n\n'), 'aria-label': kind },
      text: '⚠',
    })
  }

  function renderProductionFields() {
    const choices = productionParents(getJobs?.() || [], getPartPath?.(),
                                      { includeJobId: state.parentJobId })
    if (!choices.length) {
      mounts.fields.appendChild(el('div', {
        className: 'wizard-empty',
        children: [
          el('p', { text: 'No completed relaxation for this part yet. Production starts from equilibrated coordinates, so a relaxation has to finish first.' }),
          createButton({
            label: 'Set up a relaxation instead', variant: 'primary', size: 'sm',
            onClick: () => { setMode('relaxation') },
          }),
        ],
      }))
      return
    }

    // Which run this continues, first and on its own: everything below is a property of
    // THAT package, so changing it re-resolves the whole pane.
    //
    // The choice between a relaxation and a production is not cosmetic — off a
    // relaxation the child draws fresh velocities and is an INDEPENDENT sample; off a
    // production the velocities carry over and the child EXTENDS that trajectory. Both
    // the option labels and the help below say which one is selected.
    const chained = !!plan?.continuation
    mounts.fields.appendChild(el('section', {
      className: 'wizard-scope wizard-scope--parent',
      children: [
        el('h4', { className: 'wizard-scope__title', text: 'Continue from' }),
        el('div', {
          className: 'wizard-scope__fields',
          children: [el('div', {
            className: 'wizard-field',
            children: [
              el('label', { className: 'wizard-field__label', text: 'Run' }),
              el('div', {
                className: 'wizard-field__control',
                children: [createSelect({
                  size: 'sm', value: state.parentJobId,
                  options: choices.map(c => ({
                    value: c.job.job_id,
                    label: [c.label,
                            c.stale ? '(design has changed since)' : '',
                            c.archived ? '(archived — needs the archive drive mounted)' : '']
                      .filter(Boolean).join(' '),
                  })),
                  onChange: v => { record(); state.parentJobId = v; void loadPlan() },
                })],
              }),
              el('div', {
                className: `wizard-field__help${chained ? ' wizard-field__help--strong' : ''}`,
                text: chained
                  ? 'Coordinates, cell AND velocities carry over, so this EXTENDS that trajectory rather than sampling a new one — its frames are correlated with the parent’s. Treat the pair as one longer run. Pick the relaxation instead for an independent sample.'
                  : 'Coordinates and cell come from this run’s last unrestrained stage; velocities are drawn fresh, so several productions off one relaxation are independent samples.',
              }),
            ],
          })],
        }),
        renderInherited(),
      ],
    }))

    const fieldConds = conditionsByField(plan)
    for (const group of PRODUCTION_GROUPS) {
      const fields = PRODUCTION_FIELD_DEFS.filter(f => f.group === group.key)
      if (!fields.length) continue
      const body = el('div', { className: 'wizard-scope__fields' })
      mounts.fields.appendChild(el('section', {
        className: `wizard-scope wizard-scope--${group.key}`,
        children: [
          el('h4', { className: 'wizard-scope__title', text: group.title }),
          el('div', { className: 'wizard-scope__help', text: group.help }),
          body,
        ],
      }))
      for (const field of fields) renderField(field, fieldConds, body)
    }
  }

  /** What this run takes from the relaxation rather than choosing — stated, not offered.
   *  A production child hardlinks its parent's topology and copies its cell, so a control
   *  for any of these would be a control that does nothing. */
  function renderInherited() {
    const rows = inheritedRows(plan)
    if (!rows.length) return null
    return el('details', {
      className: 'wizard-inherited',
      attrs: { open: true },
      children: [
        el('summary', {
          text: plan?.continuation
            ? 'Inherited from the run being extended'
            : 'Inherited from this relaxation',
        }),
        el('div', {
          className: 'wizard-inherited__grid',
          children: rows.flatMap(r => [
            el('div', { className: 'wizard-inherited__label', attrs: { title: r.note },
                        text: r.label }),
            el('div', { className: 'wizard-inherited__value', attrs: { title: r.note },
                        text: r.value }),
          ]),
        }),
      ],
    })
  }

  // ── The stage table ─────────────────────────────────────────────────────────
  function renderStages() {
    mounts.stages.replaceChildren()
    if (!plan) return
    if (state.mode === 'production') { renderProductionTable(); return }

    const rows = paramRows(plan)
    const cols = stageColumns(plan)
    const badges = conditionsByStage(plan)

    const head = el('tr', {
      children: [
        el('th', { className: 'param', text: 'Parameter' }),
        ...cols.map(col => el('th', {
          className: `wizard-col wizard-col--${col.role}`,
          attrs: { title: `${col.label} — ${col.steps.toLocaleString()} steps at ${col.timestepFs} fs` },
          children: [
            el('div', { className: 'wizard-col__name', text: shortStageName(col.name) }),
            el('div', { className: 'wizard-col__meta', text: `${col.ns} ns` }),
            // Which conditions govern THIS column. A column is 118px wide, so the
            // condition's own sentence cannot live here — the label does, and the whole
            // text is one hover (or one click, which jumps to it) away.
            badges.has(col.name)
              ? el('div', { className: 'wizard-col__badge',
                            children: [conditionRefs(badges.get(col.name))] })
              : null,
          ],
        })),
      ],
    })

    const body = el('tbody')
    let group = null
    for (const row of rows) {
      if (row.group !== group) {
        group = row.group
        body.appendChild(el('tr', {
          className: 'wizard-group',
          children: [el('th', { className: 'param', attrs: { colspan: cols.length + 1 }, text: group })],
        }))
      }
      body.appendChild(el('tr', {
        children: [
          el('th', {
            className: 'param',
            attrs: { scope: 'row' },
            children: [
              document.createTextNode(row.label),
              // Editing one directive across 22 columns one cell at a time is not a
              // feature anyone would use, so every row carries a set-once affordance.
              PROTECTED_ROWS.has(row.key) ? null : el('button', {
                className: 'wizard-row-all',
                attrs: { type: 'button', title: `Set ${row.label} for EVERY stage at once` },
                text: '⋯',
                on: { click: () => editAllStages(row) },
              }),
            ],
          }),
          ...cols.map(col => {
            const cell = col.cells[row.key]
            const classes = ['wizard-cell']
            if (cell.changed) classes.push('wizard-cell--changed')
            if (cell.conditional) classes.push('wizard-cell--conditional')
            if (!cell.present) classes.push('wizard-cell--absent')
            if (cell.overridden) classes.push('wizard-cell--overridden')
            if (!cell.editable) classes.push('wizard-cell--locked')
            const title = [
              cell.changed ? `was ${cell.was} in the previous stage` : '',
              cell.overridden ? `the ${plan.preset?.label || 'protocol'} value is ${cell.protocolValue}` : '',
              cell.reason,
              cell.editable ? 'Click to edit this stage. Blank restores the protocol; “(none)” removes the directive.' : 'Not editable: this names a file the runner addresses the stage by.',
            ].filter(Boolean).join(' — ')
            const td = el('td', { className: classes.join(' '), attrs: { title }, text: cell.value })
            if (cell.editable) {
              td.tabIndex = 0
              td.addEventListener('click', () => editCell(td, col.index, row.key, cell))
              td.addEventListener('keydown', e => {
                if (e.key === 'Enter') { e.preventDefault(); editCell(td, col.index, row.key, cell) }
              })
            }
            return td
          }),
        ],
      }))
    }

    mounts.stages.appendChild(el('table', {
      children: [el('thead', { children: [head] }), body],
    }))
  }

  /**
   * The production tab-2 table.
   *
   * Column 1 is the relaxation stage this run continues from — read-only, and the
   * reference every other column's highlight is computed against. Then every stage the
   * production child really runs: the velocity-reseed bridge and the production segment
   * itself, both editable exactly as a relaxation stage is (the reseed excepted, which
   * the runner writes without an overrides pass and which therefore renders locked).
   */
  function renderProductionTable() {
    const last = plan?.source_stage
    const { rows, columns } = productionColumns(plan)
    if (!last || !columns.length) return
    const badges = conditionsByStage(plan)
    const notes = new Map((plan.asymmetries || []).map(a => [a.key, a.note]))

    const head = el('tr', {
      children: [
        el('th', { className: 'param', text: 'Parameter' }),
        ...columns.map(col => el('th', {
          className: `wizard-col wizard-col--${col.reference ? 'relaxation' : col.role}`,
          attrs: {
            title: col.reference
              ? `${col.label} — the last stage of the ${col.sourceKind} this run continues. Every highlight below is a difference from THIS column.`
              : `${col.label} — ${Number(col.steps || 0).toLocaleString()} steps at ${col.timestepFs} fs`,
          },
          children: [
            el('div', {
              className: 'wizard-col__name',
              // Name the reference column by WHAT IT IS. A chained run's reference is a
              // production stage, and heading it "Relaxation" was the one label here
              // that could send a reader to the wrong conclusion.
              text: col.reference
                ? `${col.sourceKind === 'production' ? 'Continuing' : 'Relaxation'} — ${shortStageName(col.name)}`
                : shortStageName(col.name),
            }),
            el('div', {
              className: 'wizard-col__meta',
              text: col.reference ? 'continues from' : `${col.ns} ns`,
            }),
            badges.has(col.name)
              ? el('div', { className: 'wizard-col__badge',
                            children: [conditionRefs(badges.get(col.name))] })
              : null,
          ],
        })),
      ],
    })

    const body = el('tbody')
    let group = null
    for (const row of rows) {
      if (row.group !== group) {
        group = row.group
        body.appendChild(el('tr', {
          className: 'wizard-group',
          children: [el('th', { className: 'param',
                                attrs: { colspan: columns.length + 1 }, text: group })],
        }))
      }
      const note = notes.get(row.key) || ''
      body.appendChild(el('tr', {
        children: [
          el('th', {
            className: 'param',
            attrs: { scope: 'row', title: note },
            children: [
              document.createTextNode(row.label),
              // An annotated ladder-vs-production difference: a deliberate choice with a
              // reason, and the one thing about this table that is not self-evident.
              note ? el('span', { className: 'wizard-asym', attrs: { title: note },
                                  text: '†' }) : null,
              PROTECTED_ROWS.has(row.key) ? null : el('button', {
                className: 'wizard-row-all',
                attrs: { type: 'button', title: `Set ${row.label} for EVERY stage at once` },
                text: '⋯',
                on: { click: () => editAllStages(row) },
              }),
            ],
          }),
          ...columns.map(col => {
            const cell = col.cells[row.key]
            const classes = ['wizard-cell']
            if (col.reference) classes.push('wizard-cell--reference')
            if (cell.changed) classes.push('wizard-cell--changed')
            if (cell.conditional) classes.push('wizard-cell--conditional')
            if (!cell.present) classes.push('wizard-cell--absent')
            if (cell.overridden) classes.push('wizard-cell--overridden')
            if (!cell.editable) classes.push('wizard-cell--locked')
            const title = [
              cell.changed ? `differs from the relaxation, which had ${cell.was}` : '',
              cell.overridden ? `the protocol value is ${cell.protocolValue}` : '',
              cell.reason,
              cell.editable
                ? 'Click to edit this stage. Blank restores the protocol; “(none)” removes the directive.'
                : (col.reference
                  ? 'The relaxation has already run — this column is what it did.'
                  : (col.acceptsOverrides === false
                    ? 'Not editable: the velocity-reseed bridge is written without an overrides pass.'
                    : 'Not editable: this names a file the runner addresses the stage by.')),
            ].filter(Boolean).join(' — ')
            const td = el('td', { className: classes.join(' '), attrs: { title },
                                  text: cell.value })
            if (cell.editable) {
              td.tabIndex = 0
              td.addEventListener('click', () => editCell(td, col.index, row.key, cell))
              td.addEventListener('keydown', e => {
                if (e.key === 'Enter') { e.preventDefault(); editCell(td, col.index, row.key, cell) }
              })
            }
            return td
          }),
        ],
      }))
    }

    if ((plan.asymmetries || []).length) {
      mounts.stages.appendChild(el('div', {
        className: 'wizard-note',
        children: [
          el('h4', { text: '† Production is not just the last stage without restraints' }),
          el('ul', {
            children: plan.asymmetries.map(a => el('li', {
              text: `${paramLabel(a.key)}: ${a.relaxation} → ${a.production}. ${a.note}`,
            })),
          }),
        ],
      }))
    }
    mounts.stages.appendChild(el('table', {
      children: [el('thead', { children: [head] }), body],
    }))
  }

  /**
   * Turn a cell into an input in place.
   *
   * In place rather than a popover because the value only makes sense beside its
   * neighbours: the reason to change stage 7's timestep is almost always that you can see
   * stages 6 and 8. Commits on Enter or blur, abandons on Escape.
   */
  function editCell(td, stageIndex, key, cell) {
    if (td.querySelector('input')) return
    const before = td.textContent
    const input = el('input', {
      className: 'wizard-cell__input',
      attrs: { type: 'text', value: cell.overridden ? cell.value : '' ,
               placeholder: cell.value, 'aria-label': `${key} on stage ${stageIndex}` },
    })
    let done = false
    const finish = (commit) => {
      if (done) return
      done = true
      const next = commit ? normaliseOverrideInput(input.value) : undefined
      const current = state.stageOverrides[String(stageIndex)]?.[key]
      // Committing the value that is already there is not an edit: it must not re-plan,
      // and above all it must not consume an undo.
      if (!commit || next === current) { td.textContent = before; return }
      record()
      state.stageOverrides = setStageOverride(state.stageOverrides, stageIndex, key, next)
      void loadPlan()
    }
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); finish(true) }
      // stopPropagation, or the modal's own window-level Escape handler closes the whole
      // wizard: abandoning one cell edit would throw away every other one too.
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); finish(false) }
    })
    input.addEventListener('blur', () => finish(true))
    td.replaceChildren(input)
    input.focus()
    input.select()
  }

  /** Trim the design stem off a segment name — every column repeats it otherwise. */
  function shortStageName(name) {
    const parts = String(name || '').split('_')
    const at = parts.findIndex(p => /^\d\d$|^0S$/.test(p))
    return at > 0 ? parts.slice(at).join('_') : name
  }

  /** Set one directive across every stage at once (the '*' slot). */
  function editAllStages(row) {
    const current = state.stageOverrides['*']?.[row.key] ?? ''
    // eslint-disable-next-line no-alert -- a single scalar; a modal here would be heavier
    // than the decision it collects, and the table behind it is the context.
    const next = window.prompt(
      `${row.label} — set for EVERY stage.\n\n`
      + 'Blank restores the protocol on all stages. "(none)" removes the directive.',
      current)
    if (next === null) return
    const value = normaliseOverrideInput(next)
    if (value === state.stageOverrides['*']?.[row.key]) return
    record()
    state.stageOverrides = setStageOverride(state.stageOverrides, '*', row.key, value)
    void loadPlan()
  }

  // ── Conditions ──────────────────────────────────────────────────────────────
  function renderConditions() {
    mounts.conditions.replaceChildren()
    if (!plan) return
    const groups = [
      ['Conditions', conditionBadges(plan)],
      ['If a stage crashes', (plan.retries || []).map(r => ({
        id: r.id, kind: 'retry', title: `${r.title} — retried up to ${r.max_attempts}×`,
        detail: r.detail, stages: [], allStages: true,
      }))],
      ['Decided when the system is solvated', deferredNotes(plan).map(d => ({
        id: d.key, kind: 'deferred', title: d.title, detail: d.detail, stages: [],
      }))],
    ]
    for (const [heading, items] of groups) {
      if (!items.length) continue
      mounts.conditions.appendChild(el('section', {
        className: 'wizard-cond-group',
        children: [
          el('h4', { text: heading }),
          ...items.map(c => el('div', {
            className: `wizard-cond wizard-cond--${c.kind}`,
            attrs: c.label ? { 'data-cond': String(c.id ?? c.label) } : undefined,
            children: [
              el('div', {
                className: 'wizard-cond__title',
                children: [
                  c.label ? el('span', { className: 'wizard-cond__label', text: c.label }) : null,
                  document.createTextNode(c.title),
                ],
              }),
              el('div', { className: 'wizard-cond__detail', text: c.detail }),
              c.stages?.length
                ? el('div', { className: 'wizard-cond__stages', text: `Affects: ${c.stages.map(shortStageName).join(', ')}` })
                : null,
              c.override === 'allow_undersized_cell'
                ? overrideCheckbox()
                : null,
            ],
          })),
        ],
      }))
    }
    for (const w of plan.warnings || []) {
      mounts.conditions.appendChild(el('div', { className: 'wizard-cond wizard-cond--warning',
                                                text: w }))
    }
  }

  /**
   * "(C1, C4)" — the conditions that govern whatever this sits next to.
   *
   * Written out where the condition IS (the list on the second tab) and referred to
   * everywhere it APPLIES, because a condition's explanation is a paragraph and the
   * places it applies to are a checkbox and a 118px table column. Hover gives the whole
   * text; clicking jumps to it in the list.
   */
  function conditionRefs(conds) {
    if (!conds?.length) return null
    const children = [document.createTextNode('(')]
    conds.forEach((c, i) => {
      if (i) children.push(document.createTextNode(', '))
      children.push(el('a', {
        className: 'wizard-condref',
        attrs: { href: '#', title: conditionTooltip(c) },
        text: c.label,
        on: {
          click: e => {
            e.preventDefault()
            e.stopPropagation()
            focusCondition(c.id ?? c.label)
          },
        },
      }))
    })
    children.push(document.createTextNode(')'))
    return el('span', { className: 'wizard-condrefs', children })
  }

  /** Show the condition itself — which lives on the other tab from most of its
   *  references, so this has to switch tabs before it can scroll to it. */
  function focusCondition(id) {
    setTab('plan')
    const node = mounts.conditions.querySelector(`[data-cond="${id}"]`)
    if (!node) return
    node.scrollIntoView({ block: 'center', behavior: 'smooth' })
    node.classList.add('is-flash')
    setTimeout(() => node.classList.remove('is-flash'), 1400)
  }

  function overrideCheckbox() {
    return el('label', {
      className: 'wizard-override',
      children: [
        el('input', {
          attrs: { type: 'checkbox',
                   checked: state.touched.allow_undersized_cell ? true : undefined },
          on: { change: e => setField('allow_undersized_cell', e.target.checked) },
        }),
        document.createTextNode(' Run anyway — I accept that the structure may meet its own periodic image'),
      ],
    })
  }

  function renderSummary() {
    if (state.tab === 'plan') void loadSlurmPreview()   // run length may have changed
    mounts.summary.replaceChildren()
    if (!plan) return
    const t = plan.totals || {}
    // Conditions that hold for EVERY stage are referenced once here rather than repeated
    // in 22 identical column badges.
    const everywhere = allStageConditions(plan)
    mounts.summary.appendChild(el('div', {
      className: 'wizard-totals',
      children: [
        document.createTextNode(
          `${t.n_stages} stages · ${Number(t.total_steps || 0).toLocaleString()} steps · ${t.total_ns} ns simulated`),
        everywhere.length ? document.createTextNode(' · applies throughout: ') : null,
        conditionRefs(everywhere),
      ],
    }))
    const ov = overrideSummary(state.stageOverrides)
    if (!ov.directives) return
    // A production run has no protocol of its own — it inherits the package its
    // relaxation built — so naming the relaxation's preset here would claim the edit
    // departed from something this run was never following.
    const departedFrom = state.mode === 'production'
      ? 'this run no longer matches the protocol its package records'
      : `this run is no longer the ${plan.preset?.label || 'selected protocol'}`
    mounts.summary.appendChild(el('div', {
      className: 'wizard-override-summary',
      children: [
        document.createTextNode(`⚑ ${ov.text} — ${departedFrom}. The edits are recorded `
          + `in the job's manifest and declared in its protocol-fidelity block.`),
        createButton({
          label: 'Reset every edit', variant: 'ghost', size: 'sm',
          onClick: () => {
            record()
            state.stageOverrides = clearStageOverrides()
            void loadPlan()
          },
        }),
      ],
    }))
  }

  // ── Actions ─────────────────────────────────────────────────────────────────
  function setMode(mode) {
    // Recorded because this DISCARDS every field the user set — the one change in the
    // wizard that throws work away, and so the one undo has to cover.
    record()
    state.mode = mode
    state.touched = {}
    renderSource()
    void loadPlan()
  }

  function renderSource() {
    mounts.source.replaceChildren(el('div', {
      className: 'wizard-modes',
      children: [
        modeButton('relaxation', 'Relaxation', 'Bring a freshly built design to equilibrium through the restraint-release ladder.'),
        modeButton('production', 'Production',
                   'Sample from a finished relaxation — or extend a finished production run.'),
      ],
    }))
  }

  function modeButton(mode, label, help) {
    return el('button', {
      className: `wizard-mode${state.mode === mode ? ' is-selected' : ''}`,
      attrs: { type: 'button' },
      on: { click: () => { if (state.mode !== mode) setMode(mode) } },
      children: [
        el('div', { className: 'wizard-mode__label', text: label }),
        el('div', { className: 'wizard-mode__help', text: help }),
      ],
    })
  }

  function render() {
    renderPresets()
    renderFields()
    renderStages()
    renderConditions()
    renderSummary()
    // ⚡ recommends SOLVATION and ladder settings — padding, water shell, minimisation
    // steps, fast mode. A production child re-solvates nothing, so every one of those
    // would write into a run that cannot use them.
    const prod = state.mode === 'production'
    optimizeBtn.style.display = prod ? 'none' : ''
    optimizeProgress.style.display = prod ? 'none' : ''
    paintActions()
  }

  // ONE button. Creating and running used to be a single act, which meant forces had to
  // be chosen before the job existed — and the anchors/field cards were only ever read at
  // launch, so anything picked afterwards was silently discarded. Create now always
  // stops at a prepared, not-yet-started job; forces attach to it from the panel, and the
  // panel's Run starts it.
  let createBtn = null
  let nextBtn = null
  let prevBtn = null
  let targetStep = null

  // ── Tabs ────────────────────────────────────────────────────────────────────
  const tabBtns = {}
  const panels = {}

  function setTab(tab) {
    if (state.tab === tab) return
    // Clicking a later tab is the same commitment as Next, so it obeys the same gate.
    if (tab !== 'target' && targetStep && !targetStep.isReady()) return
    state.tab = tab
    paintTabs()
  }

  // ── SLURM preview (cluster targets only) ────────────────────────────────────
  let slurmPreview = null
  let slurmBusy = false
  let slurmError = ''
  let slurmKey = ''          // partition|total_ns — refetch only when those change
  // Collapsed on every entry to the step. The stage ladder is what this step is FOR;
  // the sbatch details are for the rarer "what exactly will be submitted" question.
  let slurmOpen = false

  function paintSlurm() {
    if (!mounts.slurm) return
    if (state.target !== 'alpine') { mounts.slurm.innerHTML = ''; return }
    const summary = slurmPreview?.resources
      ? `${slurmPreview.resources.partition} · ${slurmPreview.resources.qos} · `
        + `${slurmPreview.resources.walltime} · `
        + `${Math.round(slurmPreview.resources.est_cost_su).toLocaleString()} SU`
      : slurmBusy ? 'sizing…' : 'partition, QoS, walltime, memory and the sbatch script'
    const warn = (slurmPreview?.warnings || []).length
    mounts.slurm.innerHTML = `
      <button type="button" id="wiz-slurm-toggle" aria-expanded="${slurmOpen}"
        style="width:100%;display:flex;align-items:baseline;gap:8px;margin:14px 0 0;
               background:none;border:0;padding:4px 0;cursor:pointer;text-align:left">
        <span style="color:#8b949e;font-size:10px;width:10px">${slurmOpen ? '▾' : '▸'}</span>
        <span style="font-size:12px;color:#c9d1d9;font-weight:600">SLURM request</span>
        <span style="font-size:10px;color:#6e7681">${summary}</span>
        ${warn ? '<span style="font-size:10px;color:#d29922">⚠</span>' : ''}
      </button>
      <div id="wiz-slurm-body" ${slurmOpen ? '' : 'hidden'} style="padding:6px 0 0 18px"></div>
    `
    const body = mounts.slurm.querySelector('#wiz-slurm-body')
    if (body && slurmOpen) {
      body.innerHTML = renderSlurmDetails(slurmPreview, { busy: slurmBusy, error: slurmError })
    }
    mounts.slurm.querySelector('#wiz-slurm-toggle')?.addEventListener('click', () => {
      slurmOpen = !slurmOpen
      // Sized only when actually opened: the atom estimate behind it builds the
      // design's whole heavy-atom model (~26 s on a 6-helix bundle), and most visits
      // to this step never ask the question.
      if (slurmOpen) void loadSlurmPreview()
      else paintSlurm()
    })
  }

  /**
   * Size the SLURM request for the plan currently on screen.
   *
   * Only for a cluster target, and only once per (partition, run length): the atom
   * estimate behind it builds the design's heavy-atom model, which is slow the first
   * time. Never blocks the plan table — the block fills in beside it.
   */
  async function loadSlurmPreview() {
    if (state.target !== 'alpine' || !plan || !slurmOpen) { paintSlurm(); return }
    const totalNs = Number(plan.totals?.total_ns || 0)
    const key = `${state.partition || ''}|${totalNs}`
    if (key === slurmKey && (slurmPreview || slurmBusy)) return
    slurmKey = key
    slurmBusy = true
    slurmError = ''
    paintSlurm()
    try {
      slurmPreview = await api.getSlurmPreview?.({
        cluster_name: 'alpine', partition: state.partition, total_ns: totalNs,
        job_name: 'nadoc_job',
      })
      if (!slurmPreview) slurmError = api.lastErrorMessage?.() || 'Could not size the SLURM request.'
    } catch (err) {
      slurmPreview = null
      slurmError = `Could not size the SLURM request: ${err?.message || err}`
    } finally {
      slurmBusy = false
      paintSlurm()
    }
  }

  /** Move `delta` steps through TABS from wherever we are. */
  function stepBy(delta) {
    const i = TABS.findIndex(([id]) => id === state.tab)
    const next = TABS[(i < 0 ? 0 : i) + delta]
    if (next) setTab(next[0])
  }

  function paintTabs() {
    for (const [tab, btn] of Object.entries(tabBtns)) {
      const on = tab === state.tab
      btn.classList.toggle('is-selected', on)
      btn.setAttribute('aria-selected', on ? 'true' : 'false')
    }
    for (const [tab, panel] of Object.entries(panels)) panel.hidden = tab !== state.tab
    // Entering the step always starts collapsed — the stage ladder is the subject
    // here, and the sbatch details are opt-in (and expensive to size).
    if (state.tab === 'plan') { slurmOpen = false; paintSlurm() }
    paintActions()
  }

  function tabButton(tab, label, index) {
    return el('button', {
      className: `wizard-tab${state.tab === tab ? ' is-selected' : ''}`,
      attrs: { type: 'button', role: 'tab', 'aria-selected': state.tab === tab ? 'true' : 'false' },
      on: { click: () => setTab(tab) },
      children: [
        el('span', { className: 'wizard-tab__num', text: String(index + 1) }),
        document.createTextNode(label),
      ],
    })
  }

  /** Buttons are `display:inline-flex` from their own class, so `hidden` alone would not
   *  hide them — the footer swaps them by display. */
  function showAction(btn, on) {
    if (btn) btn.style.display = on ? '' : 'none'
  }

  function paintActions() {
    const blocked = plan ? blockingConditions(plan).length > 0 : false
    const disabled = busy || !plan || blocked
    if (createBtn) {
      createBtn.disabled = disabled
      createBtn.title = blocked
        ? 'Resolve the blocking condition on the next tab first.'
        : 'Prepare the job and leave it ready to run.'
    }
    // The first step must be ANSWERED before the rest of the wizard means anything:
    // an Alpine run with no node picked would be sized against nothing.
    const onTarget = state.tab === 'target'
    const targetReady = !targetStep || targetStep.isReady()
    if (nextBtn) {
      nextBtn.disabled = busy || (onTarget && !targetReady)
      nextBtn.title = onTarget && !targetReady
        ? (targetStep?.readiness().reason || 'Choose where this job runs.')
        : ''
    }
    if (prevBtn) prevBtn.disabled = busy
    // Creating a run is offered only once its plan has been shown — the last tab is
    // where every consequence of these settings is stated.
    const idx = TABS.findIndex(([id]) => id === state.tab)
    const onPlan = state.tab === 'plan'
    showAction(nextBtn, idx < TABS.length - 1)
    showAction(prevBtn, idx > 0)
    showAction(createBtn, onPlan)
  }

  async function submit({ autostart }) {
    if (busy) return
    busy = true
    paintActions()
    try {
      if (state.mode === 'production') {
        const body = productionPayload({
          touched: state.touched, autostart,
          // The run length always reaches the request: it is the one production setting
          // with no server-side inheritance, so an omitted one would silently fall to the
          // API's 1 ns default rather than to what the form is showing.
          lengthNs: valueOf('length_ns'),
          stageOverrides: state.stageOverrides,
        })
        // Step 1's answer, spread OVER the built body: productionPayload takes camelCase
        // args, so these snake_case API fields have to land on the result, not the args.
        const job = await spawnProduction?.(state.parentJobId,
          { ...body, ...targetStep.payloadFields() })
        if (job) { onJobCreated?.(job.job_id); close() }
      } else {
        // Drop anything the server would force anyway. Sending it changes nothing, but it
        // would sit in `model_fields_set` as an explicit choice the user did not make
        // under THIS protocol — and would come back to life under the next one.
        const touched = Object.fromEntries(
          Object.entries(state.touched).filter(([k]) => !isForced(k)))
        const job = await launch?.({
          ...wizardPayload({
            presetId: state.presetId, touched, autostart,
            stageOverrides: state.stageOverrides,
          }),
          // Step 1's answer. Spread OVER the protocol payload so the wizard's choice is
          // what actually reaches the API, not the panel's older radio state.
          ...targetStep.payloadFields(),
        }, { draftId: state.draftId })
        if (job) { onJobCreated?.(job.job_id); close() }
      }
    } finally {
      busy = false
      paintActions()
    }
  }

  // ── ⚡ Optimize for this machine ─────────────────────────────────────────────
  const optimizeBtn = createButton({
    label: '⚡ Optimize for this machine', variant: 'ghost', size: 'sm',
  })
  optimizeBtn.title = 'Pick the settings that suit this design and this hardware (GPU, '
    + 'RAM, cores). Shows what it will change — and the caveats — before applying anything.'
  const optimizeProgress = el('div', { className: 'wizard-optimize-progress' })

  /** The wizard's effective settings, in the recommender's own vocabulary. */
  function currentValues() {
    const devices = String(valueOf('devices') ?? '0')
    return {
      threads: Number(valueOf('threads')) || undefined,
      compute: /^(cpu|none)$/i.test(devices) ? 'cpu' : 'gpu',
      // The recommender speaks Ångström for the shell; the request field is nm.
      water_shell_a: (Number(valueOf('water_shell_nm')) || 0) * 10,
      padding_nm: Number(valueOf('padding_nm')) || undefined,
      minimize_steps: Number(valueOf('minimize_steps')) || undefined,
      fast: !!valueOf('fast'),
      gpu_resident: valueOf('gpu_resident'),
    }
  }

  /** Apply a recommendation as if the user had typed it — so the chips read "you set
   *  this" and the values stop following the protocol, which is exactly what happened. */
  function applyRecommendation(rec = {}) {
    record()
    if (rec.threads != null) state.touched.threads = Number(rec.threads)
    if (rec.compute != null) state.touched.devices = rec.compute === 'cpu' ? 'cpu' : '0'
    if (rec.water_shell_a != null) state.touched.water_shell_nm = Number(rec.water_shell_a) / 10
    if (rec.padding_nm != null) state.touched.padding_nm = Number(rec.padding_nm)
    if (rec.minimize_steps != null) state.touched.minimize_steps = Number(rec.minimize_steps)
    if (rec.fast != null) state.touched.fast = !!rec.fast
    // The recommender speaks booleans; the control is auto/on/off. ⚡ has an OPINION, so
    // it lands on an explicit on/off rather than resetting the control to auto.
    if (rec.gpu_resident != null) state.touched.gpu_resident = rec.gpu_resident ? 'on' : 'off'
    void loadPlan()
  }

  /** The heading has to say when this is not a fresh job — a seeded draft solvates an
   *  EXISTING job rather than creating one, and "New NAMD job" would misdescribe it. */
  function modalTitle() {
    return state.draftId ? 'Set up this seeded job' : 'New NAMD job'
  }

  // ── Modal ───────────────────────────────────────────────────────────────────
  function build() {
    createBtn = createButton({
      label: 'Create job', variant: 'primary',
      onClick: () => { void submit({ autostart: false }) },
    })
    // Index arithmetic, not hardcoded ids: there are three steps now, and the next one
    // is whatever follows the current index.
    nextBtn = createButton({
      label: 'Next →', variant: 'primary',
      onClick: () => { stepBy(1) },
    })
    nextBtn.title = 'See what these settings actually run, stage by stage'
    prevBtn = createButton({
      label: '← Previous', variant: 'ghost',
      onClick: () => { stepBy(-1) },
    })
    prevBtn.title = 'Back to the previous step'
    undoBtn = createButton({ label: '↶ Undo', variant: 'ghost', size: 'sm', onClick: () => undo() })
    paintUndo()

    // Step 1 — where it runs.  Its own module owns the hardware probe, the cluster
    // login and the partition table; the wizard only holds the answer and re-paints
    // the footer gate when it changes.
    mounts.target = el('div')
    targetStep = initWizardTargetStep({
      mount: mounts.target,
      fetchHardware: api?.fetchHardware,
      fetchAvailability: api?.fetchAvailability,
      fsApi: api?.fsApi,
      initialTarget: state.target,
      onChange: ({ target, partition }) => {
        state.target = target
        state.partition = partition
        // A different node is a different SLURM request; drop the sized one.
        slurmPreview = null
        slurmKey = ''
        onTargetChange({ target, partition })
        paintActions()
      },
    })
    panels.target = el('section', {
      className: 'wizard-pane wizard-tabpanel',
      attrs: { role: 'tabpanel' },
      children: [mounts.target],
    })

    panels.setup = el('section', {
      className: 'wizard-pane wizard-tabpanel',
      attrs: { role: 'tabpanel' },
      children: [
        mounts.source,
        mounts.preset,
        el('h3', { text: 'Settings' }),
        optimizeBtn,
        optimizeProgress,
        mounts.fields,
      ],
    })
    panels.plan = el('section', {
      className: 'wizard-pane wizard-tabpanel',
      attrs: { role: 'tabpanel' },
      children: [mounts.summary, mounts.slurm, mounts.stages, mounts.conditions],
    })

    for (const [i, [tab, label]] of TABS.entries()) tabBtns[tab] = tabButton(tab, label, i)

    modal = createModal({
      title: modalTitle(),
      size: 'xl',
      className: 'modal--wizard',
      body: el('div', {
        className: 'wizard',
        children: [
          el('div', {
            className: 'wizard-tabbar',
            children: [
              el('div', { className: 'wizard-tabs', attrs: { role: 'tablist' },
                          children: Object.values(tabBtns) }),
              undoBtn,
            ],
          }),
          mounts.status,
          panels.target,
          panels.setup,
          panels.plan,
        ],
      }),
      actions: [
        createButton({ label: 'Cancel', variant: 'ghost', onClick: () => close() }),
        prevBtn,
        nextBtn,
        createBtn,
      ],
      onClose: () => { refetch.cancel() },
    })
    // Ctrl+Z anywhere in the wizard except inside a text control, where the browser's own
    // undo is the one the user means.
    modal.root.addEventListener('keydown', e => {
      if (!(e.key === 'z' || e.key === 'Z') || !(e.ctrlKey || e.metaKey) || e.shiftKey) return
      const tag = e.target?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      e.preventDefault()
      undo()
    })
    paintTabs()
    onOptimizeMount?.({ button: optimizeBtn, progressEl: optimizeProgress })
  }

  async function open(mode = null, { draftId = null, prefill = null,
    parentJobId = null } = {}) {
    if (!modal) build()
    if (mode) state.mode = mode
    state.draftId = draftId
    // Opening ON a job means continuing THAT run, not the newest one for this part —
    // which is what `ensureParent` would otherwise pick, silently, while the user had a
    // different relaxation selected in the list.
    if (parentJobId) state.parentJobId = parentJobId
    // A production session starts clean: the previous session's settings describe a
    // different parent package, so carrying them over would present another run's
    // integrator choice as this one's.
    if (state.mode === 'production' && !prefill) state.touched = {}
    // A fresh session starts on the first tab with nothing to undo — the previous run's
    // history describes settings this wizard is no longer showing.
    state.tab = 'target'
    undoStack = []
    paintUndo()
    paintTabs()
    targetStep?.render()
    restorePreferences()
    if (prefill) {
      // A draft's recorded settings arrive as TOUCHED, because they were chosen — so
      // they survive a protocol switch and their chips read "you set this".
      state.touched = { ...prefill.touched }
      if (prefill.presetId) state.presetId = prefill.presetId
    }
    renderSource()
    if (!presets.length) {
      try {
        const cat = await api.getRelaxPresets?.()
        presets = cat?.presets || []
        const preferred = presets.find(p => p.id === state.presetId && p.available !== false)
        if (!preferred) {
          state.presetId = (presets.find(p => p.available !== false) || presets[0])?.id
            || state.presetId
        }
      } catch { presets = [] }
    }
    if (modal.header) {
      const t = modal.header.querySelector('.modal__title')
      if (t) t.textContent = modalTitle()
    }
    modal.open()
    render()
    await loadPlan()
  }

  function close() {
    refetch.cancel()
    modal?.close()
  }

  return { open, close, isOpen: () => !!modal?.isOpen?.(), currentValues, applyRecommendation }
}
