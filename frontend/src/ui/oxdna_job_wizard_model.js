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
  return { valid: Object.keys(errors).length === 0, errors }
}

export function oxdnaWizardDefaults(overrides = {}) { return { ...DEFAULTS, ...overrides } }

const interval = steps => Math.max(1, Math.floor(Number(steps) / 100))

export function oxdnaStagePlan(values = {}) {
  const v = oxdnaWizardDefaults(values)
  const shared = { interaction_type: v.interaction_type, temperature: '296K', salt_concentration: Number(v.salt_concentration), topology: 'topology.top', device: String(v.device) }
  const stages = [
    { name: '1_mc_relax', purpose: 'Clear local clashes with mutual base-pair traps', ...shared,
      sim_type: 'MC', backend: 'CPU', steps: Number(v.mc_steps), ensemble: 'NVT', delta_translation: 0.1,
      delta_rotation: 0.1, max_backbone_force: 5, max_backbone_force_far: 10,
      external_forces: true, forces_file: 'forces.txt', min_bp_retained: 0,
      conf_file: 'conf.dat', last_conf_file: 'last_conf.dat', trajectory_file: 'trajectory.dat', energy_file: 'energy.dat' },
    { name: '2_md_relax', purpose: 'Relax the assembly with a capped backbone potential', ...shared,
      sim_type: 'MD', backend: v.backend, steps: Number(v.md_relax_steps), dt: 0.002,
      thermostat: 'bussi', bussi_tau: 1000, newtonian_steps: 53, max_backbone_force: 5,
      max_backbone_force_far: 10, external_forces: true, forces_file: 'forces.txt',
      min_bp_retained: Number(v.min_bp_retained), conf_file: '../1_mc_relax/last_conf.dat',
      last_conf_file: 'last_conf.dat', trajectory_file: 'trajectory.dat', energy_file: 'energy.dat' },
    { name: '3_equil', purpose: 'Verify the relaxed assembly under near-standard forces', ...shared,
      sim_type: 'MD', backend: v.backend, steps: Number(v.equil_steps), dt: 0.003,
      thermostat: 'bussi', bussi_tau: 1000, newtonian_steps: 53, max_backbone_force: 50,
      max_backbone_force_far: 100, external_forces: false, forces_file: null,
      min_bp_retained: Number(v.min_bp_retained), conf_file: '../2_md_relax/last_conf.dat',
      last_conf_file: 'last_conf.dat', trajectory_file: 'trajectory.dat', energy_file: 'energy.dat' },
  ].map(stage => ({ ...stage, print_conf_interval: interval(stage.steps), print_energy_every: interval(stage.steps) }))
  return applyOxdnaStageOverrides(stages, v.stage_overrides)
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
