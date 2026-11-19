import { createInput, el } from './primitives/index.js'

export const THERMAL_DEFAULTS = Object.freeze({ start_c: 25, end_c: 85, step_c: 5,
  block_steps: 100_000_000, stop_on_unpaired: true, unpaired_threshold: 1 })

// Old saved ramp settings may contain adaptive controls; do not submit them again.
export const THERMAL_PHYSICS_DEFAULTS = Object.freeze({ dt: 0.005, thermostat: 'brownian',
  diff_coeff: 2.5, newtonian_steps: 100, sequence_dependent: true })

export function thermalConfig(config) {
  return Object.fromEntries(Object.keys(THERMAL_DEFAULTS).map(key =>
    [key, config?.[key] ?? (key === 'stop_on_unpaired' && config ? false : THERMAL_DEFAULTS[key])]))
}

export function thermalError(config) {
  if (!config) return null
  const c = thermalConfig(config)
  for (const key of Object.keys(THERMAL_DEFAULTS))
    if (!Number.isFinite(Number(c[key]))) return `${key} must be finite.`
  if (typeof c.stop_on_unpaired !== 'boolean') return 'Choose whether to stop after melting.'
  if (!(c.unpaired_threshold > 0 && c.unpaired_threshold <= 1)) return 'Unpaired bases must be greater than 0% and at most 100%.'
  if (Math.min(c.start_c, c.end_c) <= -273.15 || Math.max(c.start_c, c.end_c) > 200) return 'Temperatures must be above −273.15 °C and at most 200 °C.'
  if (c.step_c <= 0 || c.step_c > 200 || Math.ceil(Math.abs(c.end_c - c.start_c) / c.step_c - 1e-10) > 100) return 'Choose a positive increment producing at most 101 plateaus.'
  if (!Number.isInteger(c.block_steps) || c.block_steps < 1000 || c.block_steps > 10_000_000_000) return 'Steps per temperature must be a whole number from 1,000 to 10,000,000,000.'
  return null
}

export function thermalCadence(c, requested) {
  const limit = Math.min(requested || Math.min(50_000, Math.max(1, Math.floor(c.block_steps / 100))), c.block_steps)
  const a = c.block_steps
  let best = 1
  for (let i = 1; i * i <= a; i++) if (a % i === 0)
    for (const d of [i, a / i]) if (d <= limit) best = Math.max(best, d)
  return best
}

export function thermalStages(stage, config) {
  if (!config || thermalError(config)) return [stage]
  const c = thermalConfig(config)
  const distance = Math.abs(c.end_c - c.start_c), direction = c.end_c >= c.start_c ? 1 : -1
  return Array.from({ length: Math.ceil(distance / c.step_c - 1e-10) + 1 }, (_, i) => ({ ...stage,
    name: `${i + 1}_thermal`, purpose: 'Fixed temperature dwell',
    temperature: `${Number((c.start_c + direction * Math.min(i * c.step_c, distance) + 273.15).toFixed(7))}K`,
    steps: c.block_steps, min_bp_retained: 0, max_backbone_force: null, max_backbone_force_far: null,
    refresh_vel: true,
    print_conf_interval: thermalCadence(c, stage.print_conf_interval),
    print_energy_every: thermalCadence(c, stage.print_energy_every),
  }))
}

export function thermalControls(config, onChange, { salt, concentration } = {}) {
  const root = el('fieldset', { className: 'oxdna-thermal', attrs: { 'data-thermal-controls': '' } })
  const checkbox = (label, checked, change, key) => {
    const input = el('input', { className: 'checkbox', attrs: { type: 'checkbox', 'data-thermal-field': key } })
    input.checked = checked
    input.addEventListener('change', () => change(input.checked))
    return el('label', { className: 'oxdna-thermal__toggle', children: [input, el('span', { text: label })] })
  }
  root.append(el('legend', { text: 'Thermal ramp' }), checkbox('Enable thermal ramp', !!config,
    enabled => onChange(enabled ? { ...THERMAL_DEFAULTS } : null), 'enabled'))
  if (!config) return root
  const c = thermalConfig(config)
  const update = (key, value) => onChange({ ...c, [key]: value })
  const note = text => el('p', { className: 'oxdna-thermal__help', text })
  const fields = (entries, className = '') => el('div', {
    className: `oxdna-thermal__grid ${className}`,
    children: entries.map(([key, label, help]) => {
      const input = createInput({ type: 'number', size: 'sm', data: true, step: 'any', value: key === 'unpaired_threshold' ? c[key] * 100 : c[key],
        onChange: value => update(key, Number(value) / (key === 'unpaired_threshold' ? 100 : 1)) })
      input.dataset.thermalField = key
      return el('label', { className: 'oxdna-thermal__field', children: [
        el('span', { className: 'oxdna-thermal__label', text: label }), input,
        help ? el('span', { className: 'oxdna-thermal__help', text: help }) : null,
      ] })
    }),
  })
  root.append(note('Heat or cool through temperature plateaus after relaxation. Runs locally with full-system dynamics.'),
    fields([['start_c', 'Start (°C)'], ['end_c', 'End (°C)'], ['step_c', 'Increment (°C)']], 'oxdna-thermal__grid--three'),
    fields([['block_steps', 'Steps per temperature']]))
  if (salt) {
    const temperatures = root.querySelector('.oxdna-thermal__grid--three')
    temperatures.classList.add('oxdna-thermal__grid--conditions')
    temperatures.append(salt)
  }
  if (concentration) root.insertBefore(el('div', {className:'oxdna-conditions',children:[concentration]}), root.querySelectorAll('.oxdna-thermal__grid')[1])
  root.append(checkbox('Stop series after melting', c.stop_on_unpaired, value => update('stop_on_unpaired', value), 'stop_on_unpaired'))
  if (c.stop_on_unpaired) root.append(fields([['unpaired_threshold', 'Unpaired bases (%)']]),
    note('Finish the current temperature’s full dwell, then skip later temperatures if any recorded frame meets this threshold. Counts DNA bases without any hydrogen bond, including bases that were single-stranded initially.'))
  root.append(note('New ramps use sequence-dependent oxDNA2 and a Brownian thermostat. Salt defaults to the continued job’s saved concentration. Use the simulation parameter controls to change these settings for every temperature.'))
  root.append(note('Every temperature runs for this fixed number of steps. Energy data are recorded for metrics; they do not extend or stop a stage.'))
  return root
}
