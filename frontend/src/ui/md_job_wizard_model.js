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
  return paramRowsFor((plan?.stages || []).map(s => s?.params || {}),
                      plan?.param_groups || [])
}

/** Pure: the same row list, over an explicit set of parameter maps.
 *
 *  Production's table has a column the plan's `stages` do not contain — the last
 *  relaxation stage it is being compared against — and a directive that exists ONLY
 *  there (the ladder's elastic network, its fixed atoms) is the most interesting row on
 *  the whole table. Building rows from `stages` alone silently dropped them. */
export function paramRowsFor(paramMaps, groupOrder = []) {
  const seen = new Map()          // key -> group, first-seen order preserved
  for (const params of paramMaps || []) {
    for (const key of Object.keys(params || {})) {
      if (NOISE_KEYS.has(key)) continue
      if (!seen.has(key)) seen.set(key, groupFor(key))
    }
  }
  const rows = [...seen.entries()].map(([key, group]) => ({ key, group, label: paramLabel(key) }))
  const rank = new Map((groupOrder || []).map((g, i) => [g, i]))
  return rows.sort((a, b) => {
    const ga = rank.has(a.group) ? rank.get(a.group) : (groupOrder || []).length
    const gb = rank.has(b.group) ? rank.get(b.group) : (groupOrder || []).length
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
 * Pure: the PRODUCTION tab-2 table — the relaxation stage this run continues from as a
 * read-only reference column, followed by every stage the production child will run.
 *
 * The `changed` highlight is computed against the RELAXATION column, not against the
 * previous stage: the question this table answers is "what is different about production",
 * and the reseed bridge in between is a zero-step conf nobody is comparing to.
 *
 * A stage whose `accepts_overrides` is false renders read-only throughout — the runner
 * writes that conf without an overrides pass, so an edit there would be silently dropped.
 */
export function productionColumns(plan) {
  const relax = plan?.source_stage
  if (!relax) return { rows: [], columns: [] }
  const stages = plan?.stages || []
  const rows = paramRowsFor([relax.params, ...stages.map(s => s?.params || {})],
                            plan?.param_groups || [])

  const cellsFor = (params, { reference = false, stage = null } = {}) => {
    const diff = reference ? {} : stageDiff(relax.params, params)
    const conditional = stage?.conditional_params || {}
    const overridden = stage?.overridden || {}
    const editable = !reference && stage?.accepts_overrides !== false
    const out = {}
    for (const { key } of rows) {
      out[key] = {
        value: formatValue(params?.[key]),
        present: !!params && key in params,
        changed: key in diff,
        was: key in diff ? diff[key][0] : null,
        conditional: key in conditional,
        reason: conditional[key] || '',
        overridden: key in overridden,
        protocolValue: key in overridden ? formatValue(overridden[key][0]) : null,
        editable: editable && !PROTECTED_KEYS.has(key),
      }
    }
    return out
  }

  const columns = [{
    key: '__source__',
    name: relax.name,
    label: relax.stage,
    // 'relaxation' | 'production' — the reference column's header says which, because a
    // chained run's reference IS a production stage and calling it "Relaxation" was the
    // one label on the screen that could send someone to the wrong conclusion.
    role: relax.kind === 'production' ? 'production' : 'relaxation',
    sourceKind: relax.kind || 'relaxation',
    reference: true,
    index: null,
    steps: null,
    ns: null,
    timestepFs: null,
    cells: cellsFor(relax.params, { reference: true }),
  }]
  for (const stage of stages) {
    columns.push({
      key: stage.name,
      name: stage.name,
      label: stage.stage,
      role: stage.role,
      reference: false,
      index: stage.index,
      steps: stage.steps,
      ns: stage.ns,
      timestepFs: stage.timestep_fs,
      acceptsOverrides: stage.accepts_overrides !== false,
      changedCount: Object.keys(stageDiff(relax.params, stage.params || {})).length,
      cells: cellsFor(stage.params || {}, { stage }),
    })
  }
  return { rows, columns }
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
  'box_mode', 'minimize_steps', 'adaptive_minimization', 'fast',
  'gpu_fallback_policy', 'gpu_resident', 'early_stop_relax',
  'allow_ring_pierced_seed',
  'force_soft', 'declash',
  // The three integrator axes, separated (exp51). null on any of them means "auto",
  // which the backend resolves from that run's timestep.
  'relax_timestep_fs', 'relax_rigid_bonds', 'relax_hmr',
]

/** Which kind of run a setting governs. The backend declares this (`plan.field_scopes`);
 *  this is the fallback for a plan that has not arrived yet, so the very first render
 *  already groups correctly instead of reshuffling when the plan lands. */
export const DEFAULT_FIELD_SCOPES = {
  relax_preset: 'relaxation', relax_timestep_fs: 'relaxation',
  relax_rigid_bonds: 'relaxation', relax_hmr: 'relaxation', fast: 'relaxation',
  force_soft: 'relaxation', declash: 'relaxation', early_stop_relax: 'relaxation',
  minimize_steps: 'relaxation', adaptive_minimization: 'relaxation', protocol: 'relaxation',
  gpu_resident: 'relaxation', gpu_fallback_policy: 'relaxation',
  threads: 'relaxation', devices: 'relaxation',
}

/** Pure: the scope of one field — the plan's declaration wins, then the local table,
 *  then 'both' (system-preparation settings are inherited by production because the cell
 *  and PSF are built during relaxation preparation). */
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
 * Pure: the relaxation ladder's three integrator axes, resolved to what will actually be
 * SENT with the request — not merely displayed — so an untouched wizard's shown default
 * and the job it creates can never disagree. Returns only the keys `touched` does not
 * already carry, so an explicit user choice is never overwritten.
 *
 * `wizardPayload` sends ONLY touched fields, but `relax_timestep_fs` DISPLAYS a resolved
 * default (4 fs whenever `fast` is on) via its own control `fallback` in md_job_wizard.js.
 * The backend now honors an explicit `relax_timestep_fs` verbatim on every stage — soft
 * and gentle tiers included — instead of silently capping it, so an untouched control
 * used to be harmless (auto and pinned both landed on the same capped result) and is now
 * a real divergence: the display says 4 fs, the created job ran 2. Sending the displayed
 * default as a real value keeps them in agreement; the risk condition this can trigger
 * still fires (see the backend's `relax_timestep_risk_warning`), it just no longer needs
 * a wasted click to reach it — "warn, never block"
 * (feedback_namd_4fs_production_only.md).
 *
 * `relax_rigid_bonds`/`relax_hmr` travel WITH the timestep even when it alone is
 * untouched: both mirror their own control `fallback` (kept in sync by hand — they
 * encode a fixed physical relationship, not a UI preference: RATTLE needs rigid bonds
 * above 1 fs, HMR is only load-bearing at 4 fs), and `_segment_conf` derives a
 * gentle/soft segment's actual HMR from the SEGMENT's own (already-forced-off) `fast`
 * flag, never from the pinned timestep — so pinning `dt` alone would leave a 4 fs ladder
 * silently running WITHOUT HMR on a declash design, worse than either the old capped
 * 2 fs or the 4 fs + HMR combination the wizard is actually showing.
 *
 * The timestep default mirrors `CreateJobRequest.fast`'s own server default (True)
 * directly rather than reading a plan response: on the very FIRST request, before any
 * plan has ever loaded, there is no resolved `fast` to read, and treating "no plan yet"
 * as "fast is off" would pin 2 fs, get it echoed straight back as the RESOLVED value on
 * the next call, and never self-correct.
 */
export function pinnedLadderIntegrator(touched = {}) {
  const has = (key) => Object.prototype.hasOwnProperty.call(touched, key)
  const dt = has('relax_timestep_fs')
    ? Number(touched.relax_timestep_fs)
    : (has('fast') ? !!touched.fast : true) ? 4 : 2
  const out = {}
  if (!has('relax_timestep_fs')) out.relax_timestep_fs = dt
  if (!has('relax_rigid_bonds')) out.relax_rigid_bonds = dt <= 1 ? 'none' : 'all'
  if (!has('relax_hmr')) out.relax_hmr = dt >= 4
  return out
}

/** Fields whose displayed default derives FROM `declash` (indirectly, via
 *  `pinnedLadderIntegrator`'s own logic being timestep-driven — see its doc) closely
 *  enough that a stale choice made under the OLD declash state reads as a leftover
 *  under the new one. Forcing declash on/off is a big enough decision that these
 *  three re-resolve for the new state instead of carrying a prior choice forward —
 *  e.g. a 2 fs / rigidBonds-none pin made while declash was on must not go on being
 *  sent after the user forces it off. */
const DECLASH_DEPENDENT_FIELDS = ['relax_timestep_fs', 'relax_rigid_bonds', 'relax_hmr']

/** Pure: `state.touched` after one field is set by hand — plain "set the key" for
 *  every field except `declash`, which ALSO clears its three dependent integrator
 *  axes (see DECLASH_DEPENDENT_FIELDS) so they re-derive for the state just chosen. */
export function touchedAfterSettingField(touched = {}, key, value) {
  const next = { ...touched, [key]: value }
  if (key === 'declash') {
    for (const dep of DECLASH_DEPENDENT_FIELDS) delete next[dep]
  }
  return next
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
    // Only what was touched, for the same reason the relaxation half does it: a value the
    // wizard merely DISPLAYED, sent back, marks itself explicit and overwrites the
    // package's own prep-time choice — which is precisely what a production child is
    // meant to inherit. The plan reports the resolved value either way.
    const t = state.touched || {}
    const send = (key, as = key) => {
      if (Object.prototype.hasOwnProperty.call(t, key) && t[key] != null) body[as] = t[key]
    }
    send('length_ns')
    // Raw steps, for a job whose length can only be recovered by counting what it ran (a
    // child created before its spawn request was recorded — see `jobSettingsState`). The
    // backend prefers `length_ns` and falls back to `steps`; sending NEITHER would silently
    // plan the wizard's 1 ns default over a 200 ns run.
    send('steps')
    send('dcd_freq')
    send('seed')
    send('langevin_damping')
    if (t.enm_restraints) body.enm_restraints = t.enm_restraints
    send('orientation_restraint')
    send('orientation_force_constant')
    body.allow_undersized_cell = !!t.allow_undersized_cell
  }
  if (state.nAtomsHint) body.n_atoms_hint = state.nAtomsHint
  // Sent for BOTH modes: the preview has to show the run as edited, or the highlight has
  // nothing to compute against.
  if (state.stageOverrides && Object.keys(state.stageOverrides).length) {
    body.stage_overrides = state.stageOverrides
  }
  return body
}

/**
 * Every setting the wizard may send on a production spawn, keyed by the wizard's own
 * state name. Same role `WIZARD_FIELDS` plays for a relaxation: an allowlist, so a stray
 * key in `touched` can never reach the request and 400 it.
 */
export const PRODUCTION_FIELDS = [
  'length_ns', 'steps', 'dcd_freq', 'production_timestep_fs', 'production_rigid_bonds',
  'production_hmr', 'gpu_resident', 'enm_restraints', 'langevin_damping', 'seed',
  'orientation_restraint', 'orientation_force_constant',
  'allow_undersized_cell',
]

/** Pure: the production-spawn body for `POST /md/jobs/{parent}/production-run`.
 *
 *  Like the relaxation payload, this sends ONLY what the user touched: everything else is
 *  resolved server-side from the parent package (its prep-time integrator choice, its
 *  protocol's restraint policy), and sending a value the wizard merely displayed would
 *  overwrite that inheritance with a number nobody chose. */
export function productionPayload({ touched = {}, autostart = false,
  executionTarget = 'local', clusterName = null, stageOverrides = null,
  lengthNs = null } = {}) {
  const has = k => Object.prototype.hasOwnProperty.call(touched, k)
                   && touched[k] !== undefined && touched[k] !== null
  const body = {
    // The one field with no useful server-side default: a run has to have a length, and
    // the wizard always shows one, so it is always explicit.
    length_ns: has('length_ns') ? touched.length_ns : lengthNs,
    autostart: !!autostart,
    allow_undersized_cell: !!touched.allow_undersized_cell,
    execution_target: executionTarget,
  }
  if (clusterName) body.cluster_name = clusterName
  if (has('dcd_freq')) body.dcd_freq = touched.dcd_freq
  if (has('gpu_resident')) body.gpu_resident = touched.gpu_resident
  // Pin the chosen dt to THIS run, so the trajectory matches the plan shown next to it.
  // Without it the timestep could only be chosen at prep time, and the control silently
  // had no effect on production.
  if (has('production_timestep_fs')) body.production_timestep_fs = touched.production_timestep_fs
  // The other two integrator axes. The request field names drop the `production_` prefix:
  // ProductionRunRequest is already about production, so `rigid_bonds` there is what
  // `production_rigid_bonds` is on a create request.
  if (has('production_rigid_bonds')) body.rigid_bonds = touched.production_rigid_bonds
  if (has('production_hmr')) body.hmr = touched.production_hmr
  // Whether the run keeps an elastic network, and how hard it is thermostatted. Both
  // differ from the ladder and both change what the trajectory can be compared with.
  if (has('enm_restraints')) {
    body.enm_restraints = touched.enm_restraints
  }
  if (has('langevin_damping')) body.langevin_damping = touched.langevin_damping
  if (has('orientation_restraint')) body.orientation_restraint = !!touched.orientation_restraint
  if (has('orientation_force_constant')) {
    body.orientation_force_constant = touched.orientation_force_constant
  }
  if (has('seed')) body.seed = touched.seed
  if (stageOverrides && Object.keys(stageOverrides).length) {
    body.stage_overrides = stageOverrides
  }
  return body
}

/** The two production request fields whose names differ from the wizard's own. Inverse of
 *  the rename `productionPayload` applies — see its comment. */
const PRODUCTION_REQUEST_ALIASES = { rigid_bonds: 'production_rigid_bonds', hmr: 'production_hmr' }

/**
 * Pure: total integration steps across a job's PRODUCTION segments.
 *
 * How long a run was is otherwise unrecoverable for a child whose spawn request predates
 * being recorded. The step counts are on the record and exact; the segment's stage text
 * ("0.5 ns production replica (seed 54321)") also carries it, but parsing prose is a worse
 * source than counting. A velocity-reseed bridge is excluded — it is not sampled time.
 */
export function productionSteps(job) {
  // Same test the backend applies (`md_job._is_production_segment_name`): name OR stage
  // text, plus the `_prod` short form. One definition, mirrored — not a second guess.
  const isProduction = (s) => {
    const n = String(s?.name || '').toLowerCase()
    return n.includes('production') || n.includes('_prod')
      || String(s?.stage || '').toLowerCase().includes('production')
  }
  return (job?.segments || [])
    .filter(isProduction)
    .reduce((n, s) => n + (Number(s?.steps) || 0), 0)
}

/**
 * Pure: rebuild the wizard's state from a job that has ALREADY been created, for the
 * read-only "View settings" view.
 *
 * The inverse of `wizardPayload` / `productionPayload`. A job records the request it was
 * created from (`prep_params` for a relaxation, `spawn_params` for a production child),
 * so replaying that request through `POST /md/protocol-plan` reproduces the very plan the
 * user was looking at when they pressed Create — stage table, conditions and totals
 * included, with no stored copy of any of it.
 *
 * **Why the explicit-key set matters.** The stored request is a `model_dump()`: every
 * default is materialised in it, so it cannot say which values the user actually chose.
 * The plan's provenance chips ("you set this" vs "from the protocol") are computed from
 * the request's `model_fields_set`, so replaying the dense dump would report every single
 * field as user-set. Jobs therefore also record the key set (`prep_params_set` /
 * `spawn_params_set`) and only those keys are restored, which makes the replay
 * byte-equivalent to the original request. Jobs created before that was recorded have no
 * key set; they fall back to restoring every stored value and `provenanceKnown` is false,
 * so the view can say the chips are not to be trusted rather than quietly lying.
 *
 * @param {object} job  a job record from `GET /md/jobs`
 * @returns {{available: boolean, mode: string, presetId: string|null, touched: object,
 *   stageOverrides: object, parentJobId: string|null, target: string, partition: string|null,
 *   provenanceKnown: boolean}}
 */
export function jobSettingsState(job, { forEdit = false } = {}) {
  // A run off a finished package, either way it was made: the "Production" button
  // (`run_kind`) or an ensemble fan-out (`ensemble_index`, whose replicas leave `run_kind`
  // unset). Both inherit their chemistry, cell and ladder from the parent's package, which
  // is exactly what the wizard's production mode renders.
  const production = job?.run_kind === 'production' || job?.ensemble_index != null
  const source = (production ? job?.spawn_params : job?.prep_params) || null
  const explicit = production ? job?.spawn_params_set : job?.prep_params_set
  const allowed = production ? PRODUCTION_FIELDS : WIZARD_FIELDS
  const known = Array.isArray(explicit)
  const touched = {}
  for (const [rawKey, value] of Object.entries(source || {})) {
    // Restrict to what the user chose when we know it; otherwise every stored value, which
    // is right about the VALUES and over-reports the provenance (flagged by the caller).
    // A read-only replay preserves provenance chips by restoring only what the user
    // explicitly chose. Editing instead starts every control at this job's stored value,
    // even if the protocol's default has changed since the job was created.
    if (!forEdit && known && !explicit.includes(rawKey)) continue
    const key = (production && PRODUCTION_REQUEST_ALIASES[rawKey]) || rawKey
    if (!allowed.includes(key)) continue
    if (value == null) continue
    touched[key] = value
  }
  const parentJobId = production ? (job?.parent_job_id || null) : null
  // A child created before spawn requests were recorded still has a viewable plan: the
  // protocol endpoint resolves a production run's inherited values from the ROOT
  // relaxation's own request and manifest, not from the child's. So everything except what
  // the child chose FOR ITSELF reconstructs exactly — and the two things it did choose are
  // still on the record: the velocity seed, and how long it ran (recoverable by counting
  // the steps its production segments actually carry, rather than parsing a stage label).
  if (!source && parentJobId) {
    if (job?.ensemble_seed != null) touched.seed = job.ensemble_seed
    const steps = productionSteps(job)
    if (steps) touched.steps = steps
  }
  return {
    // Viewable when there is a recorded request, OR when it is a child whose parent can
    // rebuild the plan. Only a ROOT relaxation with no request has genuinely nothing left.
    available: !!source || !!parentJobId,
    // True when there was no request to replay and the view is standing on the parent
    // instead. The two cases need different things said about them: this one reconstructs
    // faithfully, a relaxation with no key set merely cannot caption what it shows.
    rebuiltFromParent: !source && !!parentJobId,
    mode: production ? 'production' : 'relaxation',
    presetId: source?.relax_preset || null,
    touched,
    stageOverrides: source?.stage_overrides || {},
    parentJobId,
    // Where it RAN, from the job record itself rather than the request — a job submitted
    // to Alpine from the panel after being created locally has moved since.
    target: job?.execution_target || 'local',
    partition: job?.partition || null,
    // An explicit-key list means nothing without the request it indexes: a child rebuilt
    // from its parent has no per-field provenance to report, whatever it carries.
    provenanceKnown: known && !!source,
  }
}

/** Pure: what the plan says about one production setting — value, provenance, reason.
 *
 *  `production_request` is the production-resolved block (request > the parent package's
 *  prep-time value > auto); `request` is the create-request merge, which is what the four
 *  shared keys fall back to. Reading the wrong one showed the preset's 4 fs on a package
 *  whose manifest pinned 2. */
export function productionField(plan, key) {
  return plan?.production_request?.[key] || plan?.request?.[key] || null
}

/** Pure: the read-only "this comes from the relaxation" rows, in display order.
 *
 *  A production child hardlinks its parent's topology and copies its cell, so none of
 *  this is choosable here. Stating it is what turns "continue off this relaxation" into a
 *  claim the user can check. */
export function inheritedRows(plan) {
  const inh = plan?.inherited
  if (!inh) return []
  const chained = !!inh.continuation
  const rows = []
  const push = (label, value, note = '') => {
    if (value === null || value === undefined || value === '') return
    rows.push({ label, value: String(value), note })
  }
  push('Continuing from', inh.seed_stage || inh.seed_checkpoint,
       chained
         ? 'The last completed stage of the production run being extended: its '
           + 'coordinates, cell AND velocities are what this run starts from.'
         : 'The last unrestrained checkpoint of the relaxation: its coordinates and cell '
           + 'are what this run starts from.')
  if (chained) {
    push('Position in the chain',
         `run ${inh.chain_position} off this relaxation`,
         'How many production legs already sit between the relaxation this package was '
         + 'built from and this new run. Every leg shares one thermal history.')
    push('Already simulated', inh.parent_length_ns == null ? '' : `${inh.parent_length_ns} ns`,
         'The run being extended. Add this run\'s length to it for the total simulated '
         + 'time of the combined trajectory.')
  }
  push('Relaxation protocol', inh.relax_preset || inh.protocol,
       'The ladder that produced these coordinates, read from the relaxation the whole '
       + 'chain descends from. A production run has no protocol of its own — it inherits '
       + 'the package that ladder built.')
  push('Solvated atoms', inh.n_atoms == null ? '' : Number(inh.n_atoms).toLocaleString(),
       'Read from the package PSF, so the GPU-resident size gate is decided here rather '
       + 'than deferred.')
  if (Array.isArray(inh.box_ang) && inh.box_ang.length === 3) {
    push('Cell', `${inh.box_ang.map(v => `${v}`).join(' × ')} Å`,
         'Sized once, when the relaxation was solvated. Nothing after preparation '
         + 're-solvates, so a production run inherits it verbatim.')
  }
  push('Water padding', inh.padding_nm == null ? '' : `${inh.padding_nm} nm`)
  push('Water shell carve', inh.carved ? `${inh.water_shell_nm} nm — constant volume` : '',
       'A carved cell contains vacuum, so production runs NVT for the same reason the '
       + 'ladder did.')
  push('Magnesium', inh.mg_conc_mM == null ? '' : `${inh.mg_conc_mM} mM`)
  push('NaCl', inh.ion_conc_mM == null ? '' : `${inh.ion_conc_mM} mM`)
  // The ladder's BASE, which the per-stage tiers cap: a declashed or soft stage runs
  // slower than this whatever it says, so the stage table's relaxation column can
  // legitimately show a smaller number than this row does.
  push('Ladder base timestep',
       inh.ladder_timestep_fs == null ? '' : `${inh.ladder_timestep_fs} fs`,
       'What the relaxation was sized for — its per-stage tiers cap it, so an individual '
       + 'stage may have run slower. It does not constrain this run either way: a ladder '
       + 'exists to hand over equilibrated coordinates, and once it has, production is free.')
  push('Anchors', inh.anchors ? 'inherited from the relaxation' : '',
       'Sent with the run from the panel’s anchors card; an empty card means explicitly '
       + 'unanchored.')
  if (inh.field) push('Electric field', `${inh.field.field_pN} pN`)
  return rows
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

/** Pure: the same name, saying WHICH KIND of run it is.
 *
 *  Once a production run could be a parent too, "<part> run created …" stopped
 *  identifying anything: a picker holding both reads as a list of duplicates, and the
 *  choice between them is the difference between an independent sample and an extension
 *  of one trajectory. */
export function productionParentLabel(job, siblings = []) {
  const kind = job?.run_kind === 'production' ? 'production run' : 'relaxation'
  return relaxRunLabel(job, siblings).replace(' run created ', ` ${kind} created `)
}

/**
 * Pure: the completed runs a new production can start from, newest first.
 *
 * Two kinds, and the distinction is load-bearing:
 *
 * * a **relaxation** hands over equilibrated coordinates and the child draws fresh
 *   velocities, so each child is an INDEPENDENT sample;
 * * a **production** hands over coordinates *and* velocities, so the child EXTENDS that
 *   trajectory — its frames are correlated with the parent's and the pair is one longer
 *   run, not two replicas.
 *
 * An empty array is the signal for the "run a relaxation first" state.
 */
export function productionParents(jobs, partPath, { includeJobId = null } = {}) {
  const want = String(partPath || '').replace(/\\/g, '/').replace(/\/+$/, '')
  // `includeJobId` keeps a DELIBERATELY chosen parent in the list even when the part
  // filter would drop it — the user selected that run in the job list and pressed New
  // job, and silently continuing a different run is the one outcome that must not happen.
  const out = (jobs || []).filter(j =>
    isProductionParent(j)
    && (!want
        || j.job_id === includeJobId
        || String(j.design_source_path || '').replace(/\\/g, '/').replace(/\/+$/, '') === want))
  out.sort((a, b) => (b.created_at || 0) - (a.created_at || 0))
  return out.map(job => ({
    job,
    label: productionParentLabel(job, out),
    stale: !!job.out_of_date,
    // Archiving moves the job directory to the archive drive to reclaim disk; the
    // package is intact and every path that reads it honours `archive_path`, so the run
    // is still a legal parent. It is called out because the drive has to be mounted.
    archived: !!job.archived,
    // Picking this one EXTENDS a trajectory instead of sampling a new one.
    continuation: job.run_kind === 'production',
  }))
}

/** Pure: can a new production run be seeded from this job by selecting it and pressing
 *  "New job"? The mirror of `productionParents`'s own test, so the panel's detection and
 *  the wizard's picker can never disagree about what counts as a parent.
 *
 *  A completed PRODUCTION qualifies: the backend has always chained off one
 *  (`_production_seed_checkpoint` branches on `run_kind`, `build_replica_package` stages
 *  the parent's `restart.{coor,vel,xsc}` and preserves velocities), it was only the UI
 *  that had no way to ask for it.
 *
 *  Deliberately NOT excluding an archived run. Archiving is a DISK decision — the job
 *  directory moves to the archive drive and `MdJob.package_dir` follows it — not a
 *  retirement, and the spawn route accepts one. Excluding them meant that on a machine
 *  where every finished relaxation had been archived to reclaim space, production mode
 *  could only ever show "no completed relaxation for this part yet". */
export function isProductionParent(job) {
  return !!job && job.status === 'completed'
}

/**
 * Pure: the conditions panel, split by how much the user needs to care.
 *
 * `blocking` first — a cell too small to rotate in should
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

/** A condition the backend attributes to a request field, e.g. `CreateJobRequest.fast` or
 *  `ProductionRunRequest.enm_restraints`. This is the ONLY link between a condition and a
 *  settings control — it is stated by the code that raises the condition, never guessed
 *  from the wording here. Both models are accepted because a production run's controls are
 *  spread across the two: its integrator axes are create-request fields recorded at prep,
 *  while its length, restraints and coupling belong to the spawn request. */
const REQUEST_SOURCE = /^(?:CreateJobRequest|ProductionRunRequest)\.([A-Za-z_]\w*)$/

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
  // Production's own settings used to be five separate state slots; they are now ordinary
  // entries in `touched`, which is what let them render through the same field machinery
  // (provenance chips, condition references, warning icons) as every relaxation control.
  // `target`/`partition` are step 1's answer. Unlike `tab`, WHERE a job runs is a
  // property of the run, so undo must restore it.
  'mode', 'presetId', 'touched', 'stageOverrides', 'parentJobId', 'target', 'partition',
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

/** Advisory only: geometry never changes the chosen protocol behind the user's back. */
export function highAspectRatioWarning(plan, presetId, threshold = 10) {
  const ratio = Number(plan?.design?.aspect_ratio)
  if (!Number.isFinite(ratio) || ratio < threshold || presetId === 'high_aspect_ratio') return null
  return {
    ratio,
    label: 'Long filament detected',
    tooltip: 'Choose High aspect ratio (rods). Larger margin prevents high aspect ratio designs from crashing.',
  }
}
