/**
 * md_job_wizard_model.js — pure shaping for the NAMD Job Wizard.
 *
 * Everything in here is a function of its arguments: no DOM, no fetch, no module state.
 * The wizard's whole job is to tell the truth about what a run will do, and the parts
 * that decide WHAT to display are the parts most worth testing, so they live apart from
 * the parts that decide WHERE to put it.
 *
 * The protocol facts themselves come from the backend's `POST /md/protocol-plan`, which
 * builds them by running the real NAMD conf writers. Nothing here invents a parameter,
 * a default or a threshold — if a value is not in the plan, it is not shown.
 */

/** Directives the stage table never shows: per-stage output paths and restart filenames.
 *  They differ on every single column by construction, so displaying them would bury the
 *  physics under bookkeeping. Mirrors the backend's own NOISE_KEYS. */
export const NOISE_KEYS = new Set([
  'outputname', 'dcdfile', 'xstfile', 'veldcdfile', 'forcedcdfile',
  'bincoordinates', 'binvelocities', 'extendedsystem', 'coordinates', 'structure',
])

/** Directives a hand edit may not touch — they name the package's own files and outputs,
 *  so rewriting one detaches the stage from its job rather than changing the physics.
 *  The backend refuses them too (md_protocols.PROTECTED_DIRECTIVES); this is so the table
 *  can render the cell as read-only instead of letting the edit fail on submit. */
export const PROTECTED_KEYS = new Set([
  'structure', 'coordinates', 'outputname', 'dcdfile', 'xstfile',
  'veldcdfile', 'forcedcdfile', 'bincoordinates', 'binvelocities', 'extendedsystem',
  'parameters', 'paratypecharmm',
])

/** Human labels for the directives a user is most likely to be looking for. Anything
 *  absent falls back to the raw NAMD directive, which is the honest default — inventing a
 *  friendly name for a knob nobody recognises just makes it harder to look up. */
const LABELS = {
  timestep: 'Timestep (fs)',
  rigidbonds: 'Rigid bonds',
  run: 'Steps',
  minimize: 'Minimisation steps',
  gpuresident: 'GPU-resident',
  fullelectfrequency: 'PME every N steps',
  stepspercycle: 'Steps per pairlist cycle',
  pairlistdist: 'Pairlist distance (Å)',
  cutoff: 'Cutoff (Å)',
  switchdist: 'Switching distance (Å)',
  pmegridspacing: 'PME grid spacing (Å)',
  langevintemp: 'Temperature (K)',
  langevindamping: 'Langevin damping (1/ps)',
  langevinpiston: 'Barostat',
  langevinpistonperiod: 'Piston period (fs)',
  langevinpistondecay: 'Piston decay (fs)',
  langevinpistontarget: 'Pressure target (bar)',
  extrabondsfile: 'Extra bonds (restraints)',
  constraints: 'Positional restraints',
  fixedatoms: 'Fixed atoms',
  fixedatomsfile: 'Fixed-atom selection',
  dcdfreq: 'Trajectory interval (steps)',
  outputenergies: 'Energy log interval (steps)',
  restartfreq: 'Restart interval (steps)',
  xstfreq: 'Cell-trace interval (steps)',
  wrapall: 'Wrap all molecules',
  wrapwater: 'Wrap water',
  seed: 'Random seed',
}

/** Pure: display label for a NAMD directive. */
export function paramLabel(key) {
  return LABELS[key] || key
}

/**
 * Pure: the ordered rows of the stage table — the union of every stage's directives,
 * grouped, with the group order the backend declares.
 *
 * The union matters: a directive that exists in only ONE stage (the settle stage's
 * fixedAtoms, the k=0 rung dropping its elastic network) is exactly what the user is
 * looking for, and a per-stage row list would hide it.
 */
export function paramRows(plan) {
  const stages = plan?.stages || []
  const groupOrder = plan?.param_groups || []
  const seen = new Map()          // key -> group, first-seen order preserved
  for (const stage of stages) {
    for (const key of Object.keys(stage?.params || {})) {
      if (NOISE_KEYS.has(key)) continue
      if (!seen.has(key)) seen.set(key, groupFor(key))
    }
  }
  const rows = [...seen.entries()].map(([key, group]) => ({ key, group, label: paramLabel(key) }))
  const rank = new Map(groupOrder.map((g, i) => [g, i]))
  return rows.sort((a, b) => {
    const ga = rank.has(a.group) ? rank.get(a.group) : groupOrder.length
    const gb = rank.has(b.group) ? rank.get(b.group) : groupOrder.length
    return ga - gb
  })
}

/** The backend names the groups but does not tag each directive, so the mapping lives
 *  here — with an "Other" bucket so a NAMD directive nobody anticipated still appears. */
const GROUP_KEYS = {
  Integrator: ['timestep', 'rigidbonds', 'rigidtolerance', 'nonbondedfreq',
    'fullelectfrequency', 'stepspercycle', 'gpuresident', 'minimize', 'run'],
  'Electrostatics & solvent': ['pme', 'pmegridspacing', 'cutoff', 'switching', 'switchdist',
    'pairlistdist', 'exclude', 'onefourscaling', 'gbis', 'alphacutoff', 'ionconcentration',
    'solventdielectric', 'wrapall', 'wrapwater'],
  'Thermostat & barostat': ['temperature', 'langevin', 'langevintemp', 'langevindamping',
    'langevinhydrogen', 'reinitvels', 'margin', 'usegrouppressure', 'useflexiblecell',
    'useconstantarea', 'langevinpiston', 'langevinpistontarget', 'langevinpistonperiod',
    'langevinpistondecay', 'langevinpistontemp'],
  'Restraints & fixed atoms': ['extrabonds', 'extrabondsfile', 'constraints', 'consref',
    'conskfile', 'conskcol', 'constraintscaling', 'fixedatoms', 'fixedatomsfile',
    'fixedatomscol', 'efieldon', 'efield', 'colvars', 'colvarsconfig'],
  'Output cadence': ['outputenergies', 'xstfreq', 'restartfreq', 'binaryrestart', 'dcdfreq',
    'veldcdfreq', 'forcedcdfreq'],
  'Files & forcefield': ['paratypecharmm', 'parameters', 'seed'],
}

function groupFor(key) {
  for (const [group, keys] of Object.entries(GROUP_KEYS)) {
    if (keys.includes(key)) return group
  }
  return 'Other'
}

/** Pure: render a directive value for a table cell. Repeated directives arrive as an
 *  array (extraBondsFile is the one that matters) and are joined so both files show. */
export function formatValue(value) {
  if (value === undefined || value === null) return '—'
  if (Array.isArray(value)) return value.join('\n')
  return String(value)
}

/**
 * Pure: one column per stage, each carrying a cell for every row in `paramRows`.
 *
 * A cell is marked `changed` when this stage's diff (computed by the backend from the
 * confs it would write) touches that directive, and `conditional` when the value depends
 * on something solvation decides. Those two flags are the whole point of the table.
 */
export function stageColumns(plan) {
  const rows = paramRows(plan)
  return (plan?.stages || []).map(stage => {
    const params = stage?.params || {}
    const diff = stage?.diff_vs_previous || {}
    const conditional = stage?.conditional_params || {}
    const overridden = stage?.overridden || {}
    const cells = {}
    for (const { key } of rows) {
      cells[key] = {
        value: formatValue(params[key]),
        present: key in params,
        changed: key in diff,
        was: key in diff ? formatValue(diff[key][0]) : null,
        conditional: key in conditional,
        reason: conditional[key] || '',
        // A SECOND, independent highlight. `changed` answers "what moves as the ladder
        // advances"; this answers "where have I departed from the protocol I picked",
        // which is the question a reviewer asks and the one the protocol name claims.
        overridden: key in overridden,
        protocolValue: key in overridden ? formatValue(overridden[key][0]) : null,
        editable: !PROTECTED_KEYS.has(key),
      }
    }
    return {
      key: stage.name,
      name: stage.name,
      label: stage.stage,
      role: stage.role,
      index: stage.index,
      steps: stage.steps,
      ns: stage.ns,
      timestepFs: stage.timestep_fs,
      changedCount: Object.keys(diff).filter(k => !NOISE_KEYS.has(k)).length,
      cells,
    }
  })
}

/**
 * Pure: client-side mirror of the backend's stage diff.
 *
 * Used for the production comparison (two columns the client already holds) and as the
 * oracle the unit tests check the backend's shape against. `(absent)` on either side is
 * deliberate: a directive appearing or disappearing is the most important kind of
 * difference there is.
 */
export function stageDiff(prev, next, { ignore = NOISE_KEYS } = {}) {
  if (!prev) return {}
  const out = {}
  const keys = new Set([...Object.keys(prev), ...Object.keys(next || {})])
  for (const key of [...keys].sort()) {
    if (ignore.has(key)) continue
    const a = key in prev ? formatValue(prev[key]) : '(absent)'
    const b = next && key in next ? formatValue(next[key]) : '(absent)'
    if (a !== b) out[key] = [a, b]
  }
  return out
}

/**
 * Pure: the side-by-side relaxation-vs-production table.
 *
 * `rows` is every directive either column carries; `asymmetries` is the annotated subset
 * the backend flagged as a deliberate, previously-invisible difference. A production run
 * is NOT "the last ladder stage with the restraints removed", and this is where that
 * stops being a surprise.
 */
export function productionComparison(lastStageParams, productionParams, asymmetries = []) {
  const notes = new Map((asymmetries || []).map(a => [a.key, a.note]))
  const diff = stageDiff(lastStageParams, productionParams)
  const keys = new Set([
    ...Object.keys(lastStageParams || {}),
    ...Object.keys(productionParams || {}),
  ])
  const rows = [...keys]
    .filter(k => !NOISE_KEYS.has(k))
    .sort((a, b) => {
      const ca = a in diff ? 0 : 1
      const cb = b in diff ? 0 : 1
      return ca - cb || a.localeCompare(b)
    })
    .map(key => ({
      key,
      label: paramLabel(key),
      group: groupFor(key),
      relaxation: formatValue(lastStageParams?.[key]),
      production: formatValue(productionParams?.[key]),
      changed: key in diff,
      note: notes.get(key) || '',
    }))
  return { rows, asymmetries: asymmetries || [], changedCount: Object.keys(diff).length }
}

/**
 * Pure: the preset card's copy, including how many values it is actually supplying.
 *
 * The count comes from the plan's provenance, not from the preset's own defaults, so it
 * reflects what survived after the user started overriding things.
 */
export function presetSummary(preset, plan) {
  const request = plan?.request || {}
  const fromPreset = Object.keys(request).filter(k => request[k]?.provenance === 'preset')
  const overridden = Object.keys(request).filter(k => request[k]?.provenance === 'user')
  return {
    id: preset?.id || '',
    label: preset?.label || '',
    summary: preset?.summary || '',
    reference: preset?.reference || '',
    available: preset?.available !== false,
    unavailableReason: preset?.unavailable_reason || '',
    fromPreset,
    overridden,
    note: fromPreset.length
      ? `${fromPreset.length} setting${fromPreset.length === 1 ? '' : 's'} come from this protocol`
      : 'every setting has been overridden',
  }
}

/** Fields the wizard owns. Everything else on a create request — anchors, electric
 *  field, run directory, cluster target — belongs to the panel, which merges them in.
 *  `protocol` is deliberately absent: it is derived from the preset, and sending both
 *  risks a 400 when they disagree. */
export const WIZARD_FIELDS = [
  'threads', 'devices', 'salt_mode', 'mg_conc_mM', 'ion_conc_mM', 'padding_nm',
  'production_ns_intent', 'water_shell_nm', 'minimize_steps', 'fast',
  'gpu_fallback_policy', 'production_timestep_fs', 'gpu_resident', 'early_stop_relax',
  'allow_water_shell_carve', 'force_soft', 'declash',
  // The three integrator axes, separated (exp51). null on any of them means "auto",
  // which the backend resolves from that run's timestep.
  'relax_timestep_fs', 'relax_rigid_bonds', 'relax_hmr',
  'production_rigid_bonds', 'production_hmr',
]

/** Which kind of run a setting governs. The backend declares this (`plan.field_scopes`);
 *  this is the fallback for a plan that has not arrived yet, so the very first render
 *  already groups correctly instead of reshuffling when the plan lands. */
export const DEFAULT_FIELD_SCOPES = {
  relax_preset: 'relaxation', relax_timestep_fs: 'relaxation',
  relax_rigid_bonds: 'relaxation', relax_hmr: 'relaxation', fast: 'relaxation',
  force_soft: 'relaxation', declash: 'relaxation', early_stop_relax: 'relaxation',
  minimize_steps: 'relaxation', protocol: 'relaxation',
  production_timestep_fs: 'production', production_rigid_bonds: 'production',
  production_hmr: 'production', production_ns_intent: 'production',
}

/** Pure: the scope of one field — the plan's declaration wins, then the local table,
 *  then 'both' (solvation, chemistry and hardware are shared by construction: the cell
 *  and PSF a relaxation builds are what production inherits). */
export function fieldScope(key, plan) {
  return plan?.field_scopes?.[key] || DEFAULT_FIELD_SCOPES[key] || 'both'
}

/** Pure: does this field have a condition that objects to the current combination?
 *  Returns the worst kind present, or null. Drives the warning icon on the control. */
export function fieldAlert(conds) {
  if (!conds?.length) return null
  if (conds.some(c => c.kind === 'blocking')) return 'blocking'
  if (conds.some(c => c.kind === 'warning')) return 'warning'
  return null
}

/**
 * Pure: the create-job body for the wizard's current state.
 *
 * Sends ONLY the fields the user actually touched, plus the preset. This is the whole
 * reason provenance works: the server's preset merge fills anything unset, and a field
 * the wizard sent unconditionally would mark itself "explicit" and defeat the preset it
 * was supposed to be following.
 */
export function wizardPayload({ presetId, touched = {}, autostart = false,
  stageOverrides = null } = {}) {
  const body = { relax_preset: presetId, autostart: !!autostart }
  for (const key of WIZARD_FIELDS) {
    if (Object.prototype.hasOwnProperty.call(touched, key)) body[key] = touched[key]
  }
  if (stageOverrides && Object.keys(stageOverrides).length) {
    body.stage_overrides = stageOverrides
  }
  return body
}

/** Pure: the plan-request body — the same shape, plus what only a preview needs. */
export function planPayload(state = {}) {
  const body = wizardPayload(state)
  delete body.autostart
  body.kind = state.mode === 'production' ? 'production' : 'relaxation'
  if (state.mode === 'production') {
    if (state.parentJobId) body.parent_job_id = state.parentJobId
    if (state.lengthNs != null) body.length_ns = state.lengthNs
    if (state.dcdFreq != null) body.dcd_freq = state.dcdFreq
    if (state.enmRestraints) body.enm_restraints = state.enmRestraints
    if (state.langevinDamping) body.langevin_damping = state.langevinDamping
    body.allow_undersized_cell = !!state.allowUndersizedCell
  }
  if (state.nAtomsHint) body.n_atoms_hint = state.nAtomsHint
  // Sent for BOTH modes: the preview has to show the run as edited, or the highlight has
  // nothing to compute against.
  if (state.stageOverrides && Object.keys(state.stageOverrides).length) {
    body.stage_overrides = state.stageOverrides
  }
  return body
}

/** Pure: the production-spawn body for `POST /md/jobs/{parent}/production-run`. */
export function productionPayload({ lengthNs, dcdFreq, autostart = false,
  allowUndersizedCell = false, executionTarget = 'local',
  clusterName = null, gpuResident = null, timestepFs = null,
  enmRestraints = null, langevinDamping = null, stageOverrides = null } = {}) {
  const body = {
    length_ns: lengthNs,
    autostart: !!autostart,
    allow_undersized_cell: !!allowUndersizedCell,
    execution_target: executionTarget,
  }
  if (dcdFreq != null) body.dcd_freq = dcdFreq
  if (clusterName) body.cluster_name = clusterName
  if (gpuResident) body.gpu_resident = gpuResident
  // Pin the chosen dt to THIS run, so the trajectory matches the plan shown next to it.
  // Without it the timestep could only be chosen at prep time, and the control silently
  // had no effect on production.
  if (timestepFs) body.production_timestep_fs = timestepFs
  // Whether the run keeps an elastic network, and how hard it is thermostatted. Both
  // differ from the ladder and both change what the trajectory can be compared with.
  if (enmRestraints) body.enm_restraints = enmRestraints
  if (langevinDamping) body.langevin_damping = langevinDamping
  if (stageOverrides && Object.keys(stageOverrides).length) {
    body.stage_overrides = stageOverrides
  }
  return body
}

/** Pure: the part name a job was created from — the file stem of its design path. */
export function partNameFor(job) {
  const path = String(job?.design_source_path || '').replace(/\\/g, '/')
  const base = path.split('/').pop() || ''
  return base.replace(/\.[^.]+$/, '') || 'design'
}

/** Pure: local wall-clock stamp for a job's creation time (seconds since the epoch). */
export function formatCreatedAt(seconds, { withSeconds = false } = {}) {
  if (!seconds) return 'unknown time'
  const d = new Date(Number(seconds) * 1000)
  const p = n => String(n).padStart(2, '0')
  const hms = `${p(d.getHours())}:${p(d.getMinutes())}${withSeconds ? `:${p(d.getSeconds())}` : ''}`
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${hms}`
}

/**
 * Pure: how a run is NAMED wherever the user has to pick one — "<part> run created
 * YYYY-MM-DD HH:MM", never a hex job id, which the UI does not show anywhere else.
 *
 * Part-and-minute is not always unique, so a collision with a sibling adds seconds
 * rather than presenting two identical choices.
 */
export function relaxRunLabel(job, siblings = []) {
  const part = partNameFor(job)
  const base = formatCreatedAt(job?.created_at)
  const clash = (siblings || []).some(other =>
    other && other.job_id !== job?.job_id
    && partNameFor(other) === part
    && formatCreatedAt(other.created_at) === base)
  const stamp = clash ? formatCreatedAt(job?.created_at, { withSeconds: true }) : base
  return `${part} run created ${stamp}`
}

/**
 * Pure: the completed relaxations a production run can start from, newest first.
 *
 * A production child seeds from equilibrated coordinates, so only a COMPLETED job
 * qualifies; a production job itself is excluded here because chaining one is done by
 * selecting it in the job list, not by starting a new run from the wizard. An empty
 * array is the signal for the "run a relaxation first" state.
 */
export function relaxationChoices(jobs, partPath) {
  const want = String(partPath || '').replace(/\\/g, '/').replace(/\/+$/, '')
  const out = (jobs || []).filter(j =>
    j
    && j.status === 'completed'
    && j.run_kind !== 'production'
    && !j.archived
    && (!want || String(j.design_source_path || '').replace(/\\/g, '/').replace(/\/+$/, '') === want))
  out.sort((a, b) => (b.created_at || 0) - (a.created_at || 0))
  return out.map(job => ({ job, label: relaxRunLabel(job, out), stale: !!job.out_of_date }))
}

/**
 * Pure: the conditions panel, split by how much the user needs to care.
 *
 * `blocking` first — a refused water-shell carve or a cell too small to rotate in should
 * not be three scrolls below a note about output cadence.
 */
export function conditionBadges(plan) {
  const order = { blocking: 0, warning: 1, forced: 2, skip: 3, conditional: 4, stage: 5, info: 6 }
  return (plan?.conditions || [])
    .map(c => ({
      id: c.id,
      kind: c.kind || 'info',
      title: c.title || '',
      detail: c.detail || '',
      stages: Array.isArray(c.applies_to) ? c.applies_to : [],
      allStages: c.applies_to === 'all',
      source: c.source || '',
      ok: c.ok,
      override: c.override || null,
    }))
    .sort((a, b) => (order[a.kind] ?? 9) - (order[b.kind] ?? 9))
    // C1, C2, … in the order the panel lists them. A condition's paragraph is far too
    // long to repeat beside the field or the stage column it governs, so the list is the
    // one place it is written out and everywhere else refers to it by this label.
    .map((c, i) => ({ ...c, label: `C${i + 1}` }))
}

/** Pure: the full text a condition reference shows on hover — label, headline, and the
 *  whole explanation, because a reference that only repeats the headline is no use. */
export function conditionTooltip(c) {
  const head = [c?.label, c?.title].filter(Boolean).join(' — ')
  return [head, c?.detail].filter(Boolean).join('\n\n')
}

/** A condition the backend attributes to a request field, e.g. `CreateJobRequest.fast`.
 *  This is the ONLY link between a condition and a settings control — it is stated by the
 *  code that raises the condition, never guessed from the wording here. */
const REQUEST_SOURCE = /^CreateJobRequest\.([A-Za-z_]\w*)$/

/** Pure: field key -> the conditions that field is responsible for, so a control can carry
 *  its own condition references instead of leaving the user to match prose to a checkbox. */
export function conditionsByField(plan) {
  const out = new Map()
  for (const c of conditionBadges(plan)) {
    const m = REQUEST_SOURCE.exec(c.source || '')
    if (!m) continue
    if (!out.has(m[1])) out.set(m[1], [])
    out.get(m[1]).push(c)
  }
  return out
}

/** Pure: the conditions that govern EVERY stage. They deliberately never appear as a
 *  per-column reference — 22 identical badges is noise — so they are referenced once,
 *  next to the run totals. */
export function allStageConditions(plan) {
  return conditionBadges(plan).filter(c => c.allStages)
}

/** Pure: is anything in the plan a hard stop? Drives whether Create is offered. */
export function blockingConditions(plan) {
  return conditionBadges(plan).filter(c => c.kind === 'blocking' && c.ok !== true)
}

/** Pure: the "resolves once the system is solvated" notes, as displayed. */
export function deferredNotes(plan) {
  return (plan?.deferred || []).map(d => ({
    key: d.key, title: d.title || d.key, detail: d.detail || '',
  }))
}

/** Pure: a per-stage badge map, so a skipped or gated stage carries its condition in its
 *  own column instead of only in a list underneath. */
export function conditionsByStage(plan) {
  const out = new Map()
  for (const c of conditionBadges(plan)) {
    for (const name of c.stages) {
      if (!out.has(name)) out.set(name, [])
      out.get(name).push(c)
    }
  }
  return out
}

/**
 * Pure: trailing-edge debounce.
 *
 * The plan endpoint is cheap and writes nothing, so the wizard can re-request it as the
 * user types — but not on every keystroke. Returns a function with `.cancel()` so a
 * closing wizard does not fire a request into a torn-down view.
 */
export function makeDebounce(fn, ms) {
  let timer = null
  const wrapped = (...args) => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => { timer = null; fn(...args) }, ms)
  }
  wrapped.cancel = () => { if (timer) clearTimeout(timer); timer = null }
  return wrapped
}


/**
 * Pure: set one directive on one stage in a stage-override map.
 *
 * `index` is the stage's position (0 = minimisation) or the string `'*'` for every stage.
 * Passing `value === null` records a DELETION (the directive is removed from the conf);
 * passing `undefined` CLEARS the override, restoring the protocol's own value. Those are
 * deliberately different: "run this stage with no barostat" and "stop overriding the
 * barostat" are not the same instruction.
 *
 * Returns a new map; the input is never mutated.
 */
export function setStageOverride(overrides, index, key, value) {
  const out = { ...(overrides || {}) }
  const slot = String(index)
  const stage = { ...(out[slot] || {}) }
  if (value === undefined) delete stage[key]
  else stage[key] = value
  if (Object.keys(stage).length) out[slot] = stage
  else delete out[slot]
  return out
}

/** Pure: drop every override on one stage, or on all of them when `index` is omitted. */
export function clearStageOverrides(overrides, index) {
  if (index === undefined) return {}
  const out = { ...(overrides || {}) }
  delete out[String(index)]
  return out
}

/** Pure: how many directives are overridden, and on how many stages. Drives the
 *  "you have departed from this protocol" summary. */
export function overrideSummary(overrides) {
  const map = overrides || {}
  const stages = Object.keys(map).filter(k => Object.keys(map[k] || {}).length)
  const directives = new Set(stages.flatMap(k => Object.keys(map[k] || {})))
  return {
    stages: stages.length,
    directives: directives.size,
    appliesToAll: Object.keys(map['*'] || {}).length > 0,
    text: directives.size
      ? `${directives.size} directive${directives.size === 1 ? '' : 's'} edited by hand `
        + `on ${stages.includes('*') ? 'every stage' : `${stages.length} stage${stages.length === 1 ? '' : 's'}`}`
      : '',
  }
}

// ── Undo ──────────────────────────────────────────────────────────────────────
/**
 * Every part of the wizard's state a user CHOSE, and therefore every part an undo has to
 * put back. Deliberately not the plan, the preset catalogue or the open tab: those are
 * consequences of a choice, not choices, and restoring them would make undo mean two
 * different things.
 */
export const UNDOABLE_KEYS = [
  'mode', 'presetId', 'touched', 'stageOverrides', 'parentJobId', 'lengthNs', 'dcdFreq',
  'enmRestraints', 'langevinDamping', 'allowUndersizedCell',
]

/** Pure: a deep-enough copy of the undoable state. `touched` and `stageOverrides` are the
 *  only nested values, and both are one level of plain object. */
export function snapshotState(state = {}) {
  const snap = {}
  for (const key of UNDOABLE_KEYS) snap[key] = state[key]
  snap.touched = { ...(state.touched || {}) }
  snap.stageOverrides = Object.fromEntries(
    Object.entries(state.stageOverrides || {}).map(([k, v]) => [k, { ...v }]))
  return snap
}

/** Restore a snapshot onto the live state object, in place (the wizard holds one `state`
 *  reference and its closures all read through it). Returns the same object. */
export function applySnapshot(state, snap) {
  if (!snap) return state
  const restored = snapshotState(snap)
  for (const key of UNDOABLE_KEYS) state[key] = restored[key]
  return state
}

/**
 * Pure: push a snapshot onto the undo stack, dropping the oldest past `limit`.
 *
 * Snapshots are taken BEFORE a change, so an identical top-of-stack means the edit before
 * this one changed nothing — retyping a cell's existing value, re-picking the selected
 * protocol. Those must not consume an undo press, or undo appears broken.
 */
export function pushUndo(stack, snap, limit = 50) {
  const list = stack || []
  const top = list[list.length - 1]
  if (top && JSON.stringify(top) === JSON.stringify(snap)) return list
  const out = [...list, snap]
  return out.length > limit ? out.slice(out.length - limit) : out
}

/** Pure: the value a cell edit should send — trimmed, with empty meaning "clear". */
export function normaliseOverrideInput(raw) {
  const text = String(raw ?? '').trim()
  if (!text) return undefined                     // clear → back to the protocol
  if (text.toLowerCase() === '(none)') return null // explicit delete of the directive
  return text
}
