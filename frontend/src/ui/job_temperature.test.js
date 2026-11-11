// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { namdTemperature, namdTemperatureOverrides, oxdnaTemperature, oxdnaTemperatureOverrides, temperatureControl, updateTemperatureControl, namdTemperatureEdit } from './job_temperature.js'
import { oxdnaStagePlan, oxdnaWizardPayload, oxdnaProductionStagePlan, oxdnaProductionPayload } from './oxdna_job_wizard_model.js'
import { wizardPayload, productionPayload } from './md_job_wizard_model.js'

describe('job temperature', () => {
  it('keeps cold preparation and synchronizes the target thermostat, piston, and velocity initialization', () => {
    const stages = [{ index: 0, accepts_overrides: false, params: { temperature: '300', langevintemp: '300' } },
      { index: 1, params: { langevintemp: '100', temperature: '100' } },
      { index: 2, params: { langevintemp: '300', langevinpistontemp: '300', temperature: '300', reinitvels: '300' } },
      { index: 3, params: { langevintemp: '300', langevinpistontemp: '300' } }]
    const original = { '2': { dcdfreq: 500 } }
    const stageOverrides = namdTemperatureOverrides(original, stages, 293.15)
    expect(namdTemperature(stages)).toBe('300')
    expect(stageOverrides).toEqual({ '2': { dcdfreq: 500, langevintemp: 293.15, langevinpistontemp: 293.15, temperature: 293.15, reinitvels: 293.15 }, '3': { langevintemp: 293.15, langevinpistontemp: 293.15 } })
    expect(original).toEqual({ '2': { dcdfreq: 500 } })
    expect(wizardPayload({ stageOverrides }).stage_overrides).toEqual(stageOverrides)
    expect(productionPayload({ stageOverrides }).stage_overrides).toEqual(stageOverrides)
    expect(namdTemperature([])).toBeNull()
  })
  it('keeps surface temperatures on the native request path, including bulk references', () => {
    const state = { mode: 'relaxation', touched: { seed: 5 }, stageOverrides: { '1': { langevintemp: 310, langevinpistontemp: 310, dcdfreq: 500 } } }
    const result = namdTemperatureEdit(state, { request: { protocol: { value: 'electrode_equilibration_namd' } } }, 293.15)
    expect(result.touched).toEqual({ seed: 5, graphene_temperature_K: 293.15 })
    expect(result.stageOverrides).toEqual({ '1': { dcdfreq: 500 } })
  })
  it('persists oxDNA Kelvin temperature through new jobs, reopened settings and production payloads', () => {
    const stage_overrides = oxdnaTemperatureOverrides({ '2_md_relax': { dt: .001 } }, oxdnaStagePlan(), 293.15)
    const payload = oxdnaWizardPayload({ stage_overrides })
    expect(oxdnaStagePlan(payload).map(s => s.temperature)).toEqual(['293.15K', '293.15K', '293.15K'])
    expect(payload.stage_overrides['2_md_relax'].dt).toBe(.001)
    const prod = oxdnaTemperatureOverrides({}, oxdnaProductionStagePlan(), 293.15)
    expect(oxdnaProductionStagePlan(oxdnaProductionPayload({ stage_overrides: prod }))[0].temperature).toBe('293.15K')
    expect(oxdnaTemperature([{ temperature: '20C' }])).toBe(293.15)
    expect(oxdnaTemperature([{ temperature: '293.15K' }])).toBe(293.15)
    expect(oxdnaTemperature([{ temperature: '0.1' }])).toBeNull()
  })
  it('shows the Celsius equivalent, commits valid Kelvin values, and rejects an empty edit', () => {
    const onChange = vi.fn();const control = temperatureControl({ value: 293.15, help: 'Target', onChange })
    const input = control.querySelector('input')
    expect(input.classList.contains('input--sm')).toBe(true)
    expect(input.closest('.wizard-field__control')).not.toBeNull()
    expect(control.textContent).toContain('20.00 °C')
    updateTemperatureControl(control, 300);expect(input.value).toBe('300')
    input.value = '298.15';input.dispatchEvent(new Event('input'));input.dispatchEvent(new Event('change'))
    expect(control.textContent).toContain('25.00 °C');expect(onChange).toHaveBeenCalledWith(298.15)
    input.value = '';input.dispatchEvent(new Event('change'));expect(onChange).toHaveBeenCalledTimes(1)
    expect(temperatureControl({ disabled: true }).querySelector('input').disabled).toBe(true)
  })
})
