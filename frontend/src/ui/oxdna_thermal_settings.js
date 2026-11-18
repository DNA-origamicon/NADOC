import { el } from './primitives/index.js'
import { thermalRunSteps } from './oxdna_thermal_job.js'

const PHYSICS = [
  ['dt', 'Time step'], ['thermostat', 'Thermostat'],
  ['newtonian_steps', 'Thermostat update interval (steps)'], ['diff_coeff', 'Diffusion coefficient'],
  ['salt_concentration', 'Monovalent salt (M)'], ['sequence_dependent', 'Sequence-dependent base strengths'],
]
const display = value => value == null ? 'Not recorded' : typeof value === 'boolean' ? value ? 'Enabled' : 'Disabled'
  : typeof value === 'number' ? value.toLocaleString(undefined, { maximumFractionDigits: 8 }) : String(value)
const fields = entries => el('dl', { className: 'oxdna-recorded-fields', children: entries.map(([name,value]) =>
  el('div', { children: [el('dt', { text: name }), el('dd', { text: display(value) })] })) })

/** Recorded specs are authoritative; never reconstruct an old run using new defaults. */
export function thermalRecordedSettings(job) {
  const cfg = job.run_config?.thermal_ramp || {}, specs = job.stage_specs || []
  const rows = thermalRunSteps(job) || []
  const root = el('div', { className: 'oxdna-thermal-recorded' })
  root.append(el('h3', { text: 'Temperature ramp' }), fields([
    ['Start (°C)', cfg.start_c], ['End (°C)', cfg.end_c], ['Increment (°C)', cfg.step_c],
    ['Steps per temperature', cfg.block_steps], ['Temperature stages', rows.length],
    ['Progression', cfg.gate === true ? 'Historical gated protocol' : 'Fixed steps per temperature'],
  ]))
  const spec = specs.find(s => s.name === rows[0]?.name)
  root.append(el('h3', { text: 'Recorded simulation parameters' }), fields([
    ['Backend', spec?.backend ?? job.backend], ['Random seed', job.random_seed ?? job.run_config?.seed],
    ...PHYSICS.map(([key,label]) => [label, spec?.[key] ?? (key === 'salt_concentration' ? job.salt_concentration : null)]),
  ]))
  if (!spec) root.append(el('p', { className: 'wizard-note', text: 'Detailed stage parameters are unavailable. No current defaults have been substituted.' }))
  const table = el('table', { children: [el('thead', { children: [el('tr', { children:
    ['Temperature', 'Status', 'Steps', 'Time step', 'Thermostat', 'Salt (M)'].map(text => el('th',{text})) })] }),
    el('tbody', { children: rows.map(row => {
      const saved = specs.find(s => s.name === row.name)
      return el('tr', { children: [row.temperature, row.status, row.steps, saved?.dt, saved?.thermostat, saved?.salt_concentration]
        .map(value => el('td',{text:display(value)})) })
    }) })] })
  root.append(el('h3', { text: 'Temperature stages' }), el('div', { className: 'oxdna-thermal-recorded__table', children: [table] }))
  return root
}

/** Shared physics editor for queued/copied ramps, preserving saved values on save. */
export function thermalRecordedPhysicsEditor(config, onChange, { includeSalt = true } = {}) {
  return el('div', { className: 'wizard-grid', children: PHYSICS.filter(([key]) => includeSalt || key !== 'salt_concentration').map(([key,label]) => {
    const value = key === 'salt_concentration' ? config.salt_concentration : config.stage_overrides?.['1_production']?.[key]
    let input
    if (key === 'thermostat' || key === 'sequence_dependent') {
      input = el('select', { className: 'select select--sm', attrs: { 'aria-label': label }, children:
        (key === 'thermostat' ? ['', 'brownian','john','bussi','langevin'] : ['', 'true','false']).map(v =>
          el('option',{text:v === '' ? 'Keep recorded value' : key === 'sequence_dependent' ? v === 'true' ? 'Enabled' : 'Disabled' : v,attrs:{value:v}})) })
      input.value = value == null ? '' : String(value)
    } else input = el('input', { className: 'input input--sm', attrs: { type:'number',step:'any',value:value ?? '', 'aria-label':label } })
    input.addEventListener('change', () => onChange(key, input.value === '' ? undefined : key === 'thermostat' ? input.value
      : key === 'sequence_dependent' ? input.value === 'true' : Number(input.value)))
    return el('label', { className:'wizard-field', children:[el('span',{text:label}),input] })
  }) })
}

export function preserveThermalPhysics(config, job) {
  const saved = job.stage_specs?.find(s => /_thermal$/.test(s.name))
  if (!saved) return config
  const recorded = Object.fromEntries(PHYSICS.filter(([key]) => saved[key] != null).map(([key]) => [key,saved[key]]))
  return { ...config, stage_overrides: { ...config.stage_overrides,
    '1_production': { ...recorded, ...config.stage_overrides?.['1_production'] } } }
}
