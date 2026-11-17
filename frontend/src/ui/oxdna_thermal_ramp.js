import { createInput, el } from './primitives/index.js'

export const THERMAL_DEFAULTS = Object.freeze({ start_c: 25, end_c: 85, step_c: 5,
  block_steps: 1_000_000, max_steps: 10_000_000, gate: true, window_samples: 20,
  min_effective_samples: 10, consecutive_passes: 2, energy_tolerance: 0.02,
  pairing_tolerance: 0.02, check_pairing: true })

export function thermalError(config) {
  if (!config) return null
  const c = { ...THERMAL_DEFAULTS, ...config }
  for (const key of Object.keys(THERMAL_DEFAULTS).filter(k => typeof THERMAL_DEFAULTS[k] === 'number'))
    if (!Number.isFinite(Number(c[key]))) return `${key} must be finite.`
  if (Math.min(c.start_c, c.end_c) <= -273.15 || Math.max(c.start_c, c.end_c) > 200) return 'Temperatures must be above −273.15 °C and at most 200 °C.'
  if (c.step_c <= 0 || c.step_c > 200 || Math.ceil(Math.abs(c.end_c - c.start_c) / c.step_c - 1e-10) > 100) return 'Choose a positive increment producing at most 101 plateaus.'
  for (const key of ['block_steps', 'max_steps', 'window_samples', 'min_effective_samples', 'consecutive_passes'])
    if (!Number.isInteger(c[key])) return `${key} must be an integer.`
  if (c.block_steps < 1000 || c.max_steps > 200_000_000 || (c.gate && c.max_steps < c.block_steps * c.consecutive_passes)) return 'Maximum dwell must cover the required sampling blocks (1,000–200,000,000 steps).'
  if (c.gate && c.max_steps % c.block_steps) return 'Maximum dwell must be a whole number of sampling blocks.'
  if (c.window_samples < 10 || c.window_samples > 1000 || c.min_effective_samples < 5 || c.min_effective_samples > c.window_samples || (c.gate && c.block_steps < 3 * c.window_samples)) return 'Use 10–1,000 samples per window and 5 or more effective samples, no greater than the window size.'
  if (c.consecutive_passes < 1 || c.consecutive_passes > 10 || c.energy_tolerance <= 0 || c.pairing_tolerance <= 0 || c.pairing_tolerance > 1) return 'Use positive tolerances and 1–10 consecutive passing blocks.'
  return null
}

export function thermalCadence(c, requested) {
  const limit = Math.min(requested || (c.gate ? c.block_steps : Math.max(1, Math.floor(c.block_steps / 100))), c.gate ? Math.floor(c.block_steps / (3 * c.window_samples)) : c.block_steps)
  let a = c.block_steps, b = c.gate ? c.max_steps : 0
  while (b) { const rest = a % b; a = b; b = rest }
  let best = 1
  for (let i = 1; i * i <= a; i++) if (a % i === 0)
    for (const d of [i, a / i]) if (d <= limit) best = Math.max(best, d)
  return best
}

export function thermalStages(stage, config) {
  if (!config || thermalError(config)) return [stage]
  const c = { ...THERMAL_DEFAULTS, ...config }
  const distance = Math.abs(c.end_c - c.start_c), direction = c.end_c >= c.start_c ? 1 : -1
  return Array.from({ length: Math.ceil(distance / c.step_c - 1e-10) + 1 }, (_, i) => ({ ...stage,
    name: `${i + 1}_thermal`, purpose: c.gate ? 'Hold until observables stabilize, within maximum dwell' : 'Fixed temperature dwell',
    temperature: `${Number((c.start_c + direction * Math.min(i * c.step_c, distance) + 273.15).toFixed(7))}K`,
    steps: c.block_steps, min_bp_retained: 0, max_backbone_force: null, max_backbone_force_far: null,
    refresh_vel: true,
    print_conf_interval: thermalCadence(c, stage.print_conf_interval),
    print_energy_every: thermalCadence(c, stage.print_energy_every),
  }))
}

export function thermalControls(config, onChange) {
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
  const c = { ...THERMAL_DEFAULTS, ...config }
  const update = (key, value) => onChange({ ...c, [key]: value })
  const note = text => el('p', { className: 'oxdna-thermal__help', text })
  const fields = (entries, className = '') => el('div', {
    className: `oxdna-thermal__grid ${className}`,
    children: entries.map(([key, label, help]) => {
      const input = createInput({ type: 'number', size: 'sm', data: true, step: 'any', value: c[key],
        onChange: value => update(key, Number(value)) })
      input.dataset.thermalField = key
      return el('label', { className: 'oxdna-thermal__field', children: [
        el('span', { className: 'oxdna-thermal__label', text: label }), input,
        help ? el('span', { className: 'oxdna-thermal__help', text: help }) : null,
      ] })
    }),
  })
  root.append(note('Heat or cool through temperature plateaus after relaxation. Runs locally with full-system dynamics.'),
    fields([['start_c', 'Start (°C)'], ['end_c', 'End (°C)'], ['step_c', 'Increment (°C)']], 'oxdna-thermal__grid--three'),
    checkbox('Wait for stability at each temperature', c.gate, value => update('gate', value), 'gate'),
    fields([
      ['block_steps', c.gate ? 'Steps per sampling block' : 'Steps per temperature'],
      ...(c.gate ? [['max_steps', 'Maximum steps per temperature']] : []),
    ]))
  if (c.gate) root.append(
    el('h4', { className: 'oxdna-thermal__heading', text: 'Stability criteria' }),
    fields([
      ['window_samples', 'Samples per window'],
      ['min_effective_samples', 'Effective samples per window', 'Minimum after accounting for correlation.'],
      ['consecutive_passes', 'Consecutive passing blocks'],
    ], 'oxdna-thermal__grid--three'),
    checkbox('Also check geometric base-pairing fraction', c.check_pairing, value => update('check_pairing', value), 'check_pairing'),
    note('Disable the pairing check for unpaired systems. A low, stable pairing fraction is allowed.'),
    fields([
      ['energy_tolerance', 'Energy tolerance', 'oxDNA energy units per particle'],
      ['pairing_tolerance', 'Pairing tolerance', 'Fraction of designed base pairs'],
    ]),
    note('Three successive windows must have stable means and drift. The job stops at the dwell limit if the checks do not pass.'))
  root.append(note('Observable stability is not proof of equilibrium or melting-temperature accuracy. Compare independent runs and heating/cooling histories.'))
  return root
}
