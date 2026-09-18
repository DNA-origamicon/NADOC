// GPU default is user-authorized; further convergence and sampling checks are
// required for DNA/protein and fixed gold/strep/DNA (TD-OXDNA-PHYSICS).
const DEFAULTS = Object.freeze({
  backend: 'CUDA', device: '0', salt_concentration: 0.5,
  interaction_type: 'DNA2',
  engine_variant: 'auto',
  mc_steps: 1000, md_relax_steps: 1_000_000, equil_steps: 100_000,
  min_bp_retained: 0.5, max_relax_retries: 3,
})

export const OXDNA_ENGINE_VARIANTS = Object.freeze(['auto', 'adaptive-memory', 'dnanm', 'upstream'])

export function validateOxdnaWizard(values = {}) {
  const v = oxdnaWizardDefaults(values)
  const errors = {}
  if (!['CUDA', 'CPU'].includes(v.backend)) errors.backend = 'Choose the CUDA or CPU backend.'
  if (!['DNA2', 'DNA'].includes(v.interaction_type)) errors.interaction_type = 'Choose oxDNA2 or oxDNA1.'
  if (!OXDNA_ENGINE_VARIANTS.includes(v.engine_variant)) errors.engine_variant = 'Choose a supported engine build.'
  if (!String(v.device).trim()) errors.device = 'Enter a CUDA device.'
  const range = (key, min, max, message) => {
    const n = Number(v[key])
    if (!Number.isFinite(n) || n < min || (max != null && n > max)) errors[key] = message
  }
  range('salt_concentration', 0.01, null, 'Salt concentration must be at least 0.01 M.')
  for (const key of ['mc_steps', 'md_relax_steps', 'equil_steps'])
    range(key, 100, null, 'Each stage must run for at least 100 steps.')
  range('min_bp_retained', 0, 1, 'Base-pair retention must be between 0 and 1.')
  range('max_relax_retries', 0, 3, 'Retries must be between 0 and 3.')
  for (const stage of oxdnaStagePlan(v)) {
    if (stage.sim_type !== 'MD') continue
    if (!['bussi', 'john', 'brownian', 'langevin', 'no'].includes(stage.thermostat))
      errors.thermostat = 'Choose bussi, john, brownian, langevin, or no thermostat.'
    if (['john', 'brownian', 'langevin'].includes(stage.thermostat)
      && !(Number.isFinite(Number(stage.diff_coeff)) && Number(stage.diff_coeff) > 0))
      errors.diff_coeff = 'Enter a positive diffusion coefficient for each local-bath stage.'
    if (!(Number.isFinite(Number(stage.dt)) && Number(stage.dt) > 0)) errors.dt = 'Time step must be positive.'
  }
  return { valid: Object.keys(errors).length === 0, errors }
}

export function oxdnaWizardDefaults(overrides = {}) { return { ...DEFAULTS, ...overrides } }

const interval = steps => Math.max(1, Math.floor(Number(steps) / 100))

export function oxdnaStagePlan(values = {}) {
  const v = oxdnaWizardDefaults(values)
  const interaction = v.protein_present ? 'DNANM' : v.interaction_type
  const shared = { ...(interaction === 'DNA2' ? { use_average_seq: false, seq_dep_file: '../oxDNA2_average_sequence_parameters.txt' } : {}), interaction_type: interaction, ...(v.protein_present ? { parfile: 'anm.par' } : {}), temperature: '296K', salt_concentration: Number(v.salt_concentration), topology: 'topology.top', device: String(v.device) }
  const stages = [
    { name: '1_mc_relax', purpose: 'Clear local clashes with mutual base-pair traps', ...shared,
      sim_type: 'MC', backend: 'CPU', steps: Number(v.mc_steps), ensemble: 'NVT', delta_translation: 0.1,
      delta_rotation: 0.1, max_backbone_force: 5, max_backbone_force_far: 10,
      external_forces: true, forces_file: 'forces.txt', min_bp_retained: 0,
      conf_file: 'conf.dat', last_conf_file: 'last_conf.dat', trajectory_file: 'trajectory.dat', energy_file: 'energy.dat' },
    { name: '2_md_relax', purpose: 'Relax the assembly with a capped backbone potential', ...shared,
      sim_type: 'MD', backend: v.backend, steps: Number(v.md_relax_steps), dt: 0.002,
      thermostat: 'bussi', diff_coeff: null, refresh_vel: true, bussi_tau: 1000, newtonian_steps: 53, max_backbone_force: 5,
      max_backbone_force_far: 10, external_forces: true, forces_file: 'forces.txt',
      min_bp_retained: Number(v.min_bp_retained), conf_file: '../1_mc_relax/last_conf.dat',
      last_conf_file: 'last_conf.dat', trajectory_file: 'trajectory.dat', energy_file: 'energy.dat' },
    { name: '3_equil', purpose: 'Verify the relaxed assembly under near-standard forces', ...shared,
      sim_type: 'MD', backend: v.backend, steps: Number(v.equil_steps), dt: 0.003,
      thermostat: 'bussi', diff_coeff: null, refresh_vel: true, bussi_tau: 1000, newtonian_steps: 53, max_backbone_force: 50,
      max_backbone_force_far: 100, external_forces: false, forces_file: null,
      min_bp_retained: Number(v.min_bp_retained), conf_file: '../2_md_relax/last_conf.dat',
      last_conf_file: 'last_conf.dat', trajectory_file: 'trajectory.dat', energy_file: 'energy.dat' },
  ].map(stage => ({ ...stage, print_conf_interval: interval(stage.steps), print_energy_every: interval(stage.steps) }))
  for (const stage of stages) {
    if (v.protein_present) {
      stage.min_bp_retained = 0
      stage.external_forces = true
      stage.fix_diffusion = false
      if (stage.name === '3_equil') stage.forces_file = 'equil_forces.txt'
    }
  }
  const resolved = applyOxdnaStageOverrides(stages, v.stage_overrides)
  if (v.fixed_core_present) for (const stage of resolved) {
    stage.external_forces = true
    stage.fix_diffusion = false
    if (stage.sim_type === 'MD') stage.dt = Math.min(stage.dt, 0.0001)
  }
  return resolved
}

export function applyOxdnaStageOverrides(stages, overrides = {}) {
  return stages.map(stage => ({ ...stage, ...(overrides?.[stage.name] || {}) }))
}

export function oxdnaWizardPayload(values, targetFields = {}) {
  const v = oxdnaWizardDefaults(values)
  return { backend: v.backend, device: String(v.device), interaction_type: v.interaction_type,
    engine_variant: v.engine_variant,
    salt_concentration: Number(v.salt_concentration),
    mc_steps: Number(v.mc_steps), md_relax_steps: Number(v.md_relax_steps), equil_steps: Number(v.equil_steps),
    min_bp_retained: Number(v.min_bp_retained), max_relax_retries: Number(v.max_relax_retries),
    stage_overrides: v.stage_overrides || {},
    ...(Number.isInteger(Number(v.seed)) && Number(v.seed) > 0 ? { seed: Number(v.seed) } : {}),
    ...targetFields }
}

export function oxdnaConfigDocument(values, targetFields = {}) {
  const payload = oxdnaWizardPayload(values, targetFields)
  const target = ['# NADOC oxDNA job', `execution_target = ${payload.execution_target || 'local'}`,
    `engine_variant = ${payload.engine_variant}`,
    ...(payload.partition ? [`partition = ${payload.partition}`] : []),
    ...(payload.runpod_gpu_key ? [`runpod_gpu_key = ${payload.runpod_gpu_key}`] : []),
    ...(payload.seed ? [`seed = ${payload.seed}`] : []),
    `max_relax_retries = ${payload.max_relax_retries}`]
  const blocks = oxdnaStagePlan(values).map(stage => {
    const lines = Object.entries(stage).filter(([key, value]) => key !== 'purpose' && value != null)
      .map(([key, value]) => `${key} = ${value === true ? 'true' : value === false ? 'false' : value}`)
    return `# ${stage.name}: ${stage.purpose}\n${lines.join('\n')}`
  })
  return `${target.join('\n')}\n\n${blocks.join('\n\n')}`
}

export function oxdnaRunpodPlanShape(values = {}) {
  const stages = oxdnaStagePlan(values)
  return { n_atoms: null, relax_ns: 0, relax_steps: stages.reduce((n, s) => n + s.steps, 0),
    relax_timestep_fs: 1, production_ns: 0, production_steps: 0, production_timestep_fs: 1,
    production_source: 'none', stages: stages.map(s => ({ steps: s.steps, dcd_freq: s.print_conf_interval })) }
}

// ── Production ("Full Sim" continuation of a completed relaxation) ─────────────
// Matches #oxdna-jobs-prod-steps / -steps-per-frame's prior UI defaults — NOT
// RunRequest's own schema default (2,000,000) — so this isn't a silent UX change.
const PRODUCTION_DEFAULTS = Object.freeze({ steps: 5_000_000, steps_per_frame: 10_000 })

export function oxdnaProductionDefaults(overrides = {}) { return { ...PRODUCTION_DEFAULTS, ...overrides } }

export function validateOxdnaProductionWizard(values = {}) {
  const v = oxdnaProductionDefaults(values)
  const errors = {}
  if (!v.parentJobId) errors.parentJobId = 'Choose a completed relaxation to continue from.'
  const range = (key, min, max, message) => {
    const n = Number(v[key])
    if (!Number.isFinite(n) || n < min || (max != null && n > max)) errors[key] = message
  }
  // Bounds match RunRequest (backend/api/routes_oxdna.py): steps 1e3-2e8, steps_per_frame 1-2e8.
  range('steps', 1000, 200_000_000, 'Production steps must be between 1,000 and 200,000,000.')
  range('steps_per_frame', 1, 200_000_000, 'Steps/frame must be between 1 and 200,000,000.')
  return { valid: Object.keys(errors).length === 0, errors }
}

/** Single-stage plan mirroring oxdnaStagePlan's shape, for the wizard's read-only summary.
 *  backend/device/salt are always inherited from the parent — RunRequest has no override field. */
export function oxdnaProductionStagePlan(values = {}, parentJob = {}) {
  const v = oxdnaProductionDefaults(values)
  return [{
    name: '1_production', purpose: 'Sample from the relaxed structure', sim_type: 'MD',
    backend: parentJob?.backend ?? null, device: parentJob?.device ?? null,
    salt_concentration: parentJob?.salt_concentration ?? null,
    steps: Number(v.steps), print_conf_interval: Number(v.steps_per_frame),
  }]
}

/** Payload sent to POST /oxdna/jobs/{parentId}/run. Deliberately excludes field/surface/anchors —
 *  those stay sourced from the shared Anchors/Electric-field/Hard-surface panel state at submit
 *  time in oxdna_jobs_panel.js, exactly as the (removed) Full Sim button already did. */
export function oxdnaProductionPayload(values) {
  const v = oxdnaProductionDefaults(values)
  return { steps: Number(v.steps), steps_per_frame: Number(v.steps_per_frame) }
}

/** Jobs eligible as a production "Continue from" parent: completed, and belonging to the current
 *  design (unless includeJobId names one already chosen — e.g. by the panel's selected-job seed —
 *  which must survive even if the part-path filter would otherwise drop it). Newest first. */
export function oxdnaProductionParents(jobs, partPath, { includeJobId = null } = {}) {
  const norm = p => String(p || '').replace(/\\/g, '/').replace(/\/+$/, '')
  const want = norm(partPath)
  return (jobs || [])
    .filter(j => j?.status === 'completed')
    .filter(j => !want || j.job_id === includeJobId || norm(j.design_source_path) === want)
    .sort((a, b) => (b.created_at || 0) - (a.created_at || 0))
}
