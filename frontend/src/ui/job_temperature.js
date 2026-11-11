import { el, createInput } from './primitives/index.js'

/** Temperatures are edits to the existing, persisted stage configurations. */
export function namdTemperature(stages = []) {
  return stages.filter(s => Number(s.params?.langevintemp) > 0).at(-1)?.params.langevintemp ?? null
}

export function namdTemperatureOverrides(overrides, stages, kelvin) {
  const target = Number(namdTemperature(stages))
  const out = structuredClone(overrides || {})
  for (const stage of stages) {
    if (stage.accepts_overrides === false) continue
    const params = stage.params || {}
    // Keep the low-temperature preparation schedule; edit the target-temperature stages.
    if (!(Number(params.langevintemp) >= target && Number(params.langevintemp) > 0)) continue
    const slot = String(stage.index)
    out[slot] = { ...(out[slot] || {}), langevintemp: kelvin }
    for (const key of ['langevinpistontemp', 'temperature', 'reinitvels']) {
      if (Number(params[key]) > 0) out[slot][key] = kelvin
    }
  }
  return out
}

export function oxdnaTemperature(stages = []) {
  const text = String(stages.at(-1)?.temperature ?? '')
  const match = text.match(/^([\d.]+)\s*([KC])$/i)
  return match ? Number(match[1]) + (match[2].toUpperCase() === 'C' ? 273.15 : 0) : null
}

export function oxdnaTemperatureOverrides(overrides, stages, kelvin) {
  const out = structuredClone(overrides || {})
  for (const stage of stages) out[stage.name] = { ...(out[stage.name] || {}), temperature: `${kelvin}K` }
  return out
}

export function temperatureControl({ value, disabled = false, help, onChange }) {
  const input = createInput({ type: 'number', size: 'sm', min: 270, max: 350, step: 0.01,
    value: value ?? '', disabled })
  input.dataset.jobTemperature = ''
  input.setAttribute('aria-label', 'Temperature (K)')
  const equivalent = el('span', { className: 'wizard-chip' })
  const update = () => { equivalent.textContent = input.value && input.checkValidity() ? `${(Number(input.value) - 273.15).toFixed(2)} °C` : '270–350 K' }
  input.addEventListener('input', update)
  input.addEventListener('change', () => {
    if (!input.value || !input.checkValidity()) { input.reportValidity(); return }
    onChange(Number(input.value))
  })
  update()
  return el('label', { className: 'wizard-field wizard-temperature', children: [
    el('span', { className: 'wizard-field__label', text: 'Temperature (K)' }), el('div', { className: 'wizard-field__control', children: [input] }), equivalent,
    el('span', { className: 'wizard-field__help', text: help }),
  ] })
}

export function updateTemperatureControl(root, value) {
  const input = root?.querySelector('[data-job-temperature]')
  if (!input || input === document.activeElement) return
  input.value = value ?? ''
  input.dispatchEvent(new Event('input'))
}

export function namdTemperatureEdit(state, plan, kelvin) {
  const surface = state.mode !== 'production' && (plan?.request?.graphene_only?.value
    || plan?.request?.two_electrodes?.value || plan?.request?.protocol?.value === 'electrode_equilibration_namd')
  // Surface preparation also writes temperature-dependent bulk-reference inputs.
  // Its existing request field owns those inputs and its differently indexed stage table.
  if (surface) {
    const stageOverrides = structuredClone(state.stageOverrides || {})
    for (const [slot, params] of Object.entries(stageOverrides)) {
      for (const key of ['langevintemp', 'langevinpistontemp', 'temperature', 'reinitvels']) delete params[key]
      if (!Object.keys(params).length) delete stageOverrides[slot]
    }
    return { touched: { ...state.touched, graphene_temperature_K: kelvin }, stageOverrides }
  }
  return { touched: state.touched, stageOverrides: namdTemperatureOverrides(state.stageOverrides, plan?.stages || [], kelvin) }
}
