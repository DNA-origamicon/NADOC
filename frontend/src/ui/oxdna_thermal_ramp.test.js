// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { THERMAL_DEFAULTS, thermalCadence, thermalControls, thermalError, thermalStages } from './oxdna_thermal_ramp.js'
import { oxdnaProductionPayload, oxdnaProductionStagePlan, validateOxdnaProductionWizard } from './oxdna_job_wizard_model.js'

describe('thermal ramps', () => {
  it('includes endpoints for heating and cooling and preserves resolved physics', () => {
    const cfg = { ...THERMAL_DEFAULTS, start_c: 36, end_c: 25, step_c: 5 }
    const stages = thermalStages({ dt: .0001, interaction: 'CpdDNA2' }, cfg)
    expect(stages.map(s => s.temperature)).toEqual(['309.15K', '304.15K', '299.15K', '298.15K'])
    expect(stages.every(s => s.dt === .0001 && s.interaction === 'CpdDNA2' && s.min_bp_retained === 0)).toBe(true)
    expect(thermalStages({}, { ...cfg, start_c: 25, end_c: 36 }).map(s => s.temperature)).toEqual(['298.15K', '303.15K', '308.15K', '309.15K'])
    expect(thermalStages({ name: 'original' }, null)).toEqual([{ name: 'original' }])
    expect(thermalStages({}, { ...cfg, start_c: 25.4, end_c: 25.7, step_c: .1 })).toHaveLength(4)
  })
  it('rejects unsafe bounds and matches exact budget cadence', () => {
    expect(thermalError(THERMAL_DEFAULTS)).toBeNull()
    expect(THERMAL_DEFAULTS.block_steps).toBe(10_000_000)
    expect(THERMAL_DEFAULTS.max_steps).toBeUndefined()
    expect(thermalCadence(THERMAL_DEFAULTS)).toBe(50_000)
    expect(thermalError({ ...THERMAL_DEFAULTS, gate: false, block_steps: 20000000 })).toBeNull()
    expect(thermalCadence({ ...THERMAL_DEFAULTS, gate: false }, 10000)).toBe(10000)
    for (const bad of [{ step_c: 0 }, { start_c: NaN }, { block_steps: 999 }, { block_steps: 200000001 }, { block_steps: 1000.5 }])
      expect(thermalError({ ...THERMAL_DEFAULTS, ...bad })).toBeTruthy()
    const cadence = thermalCadence(THERMAL_DEFAULTS, 9876)
    expect(cadence).toBeLessThanOrEqual(9876)
    expect(THERMAL_DEFAULTS.block_steps % cadence).toBe(0)
  })
  it('round-trips the production payload and previews every plateau', () => {
    const values = { parentJobId: 'parent', thermal_ramp: { ...THERMAL_DEFAULTS } }
    expect(oxdnaProductionPayload(values).thermal_ramp).toEqual(THERMAL_DEFAULTS)
    expect(oxdnaProductionStagePlan(values)).toHaveLength(13)
    expect(validateOxdnaProductionWizard(values).valid).toBe(true)
    expect(validateOxdnaProductionWizard({ ...values, stage_overrides: { '1_production': { thermostat: 'no' } } }).valid).toBe(false)
    expect(oxdnaProductionPayload({}).thermal_ramp).toBeUndefined()
  })
  it('enables the panel, edits fixed duration and disables the ramp', () => {
    let value = null
    const mount = document.createElement('div')
    document.body.append(mount)
    const draw = () => mount.replaceChildren(thermalControls(value, next => { value = next; draw() }))
    draw()
    mount.querySelector('[data-thermal-field="enabled"]').click()
    expect(value).toEqual(THERMAL_DEFAULTS)
    const end = mount.querySelector('[data-thermal-field="end_c"]')
    end.value = '95'; end.dispatchEvent(new Event('change'))
    expect(value.end_c).toBe(95)
    expect(mount.querySelector('[data-thermal-field="gate"]')).toBeNull()
    expect(mount.querySelector('[data-thermal-field="max_steps"]')).toBeNull()
    expect(mount.querySelector('[data-thermal-field="energy_tolerance"]')).toBeNull()
    mount.querySelector('[data-thermal-field="enabled"]').click()
    expect(value).toBeNull()
    mount.remove()
  })
})


it('strips obsolete gate controls from saved jobs and gives every temperature the same duration', () => {
  const values = { parentJobId: 'parent', thermal_ramp: { ...THERMAL_DEFAULTS, block_steps: 123000,
    gate: true, max_steps: 1000000, consecutive_passes: 5, energy_tolerance: .0001 } }
  expect(oxdnaProductionPayload(values).thermal_ramp).toEqual({ ...THERMAL_DEFAULTS, block_steps: 123000 })
  expect(oxdnaProductionPayload({ ...values, steps: -1 }).steps).toBe(123000)
  expect(validateOxdnaProductionWizard({ ...values, steps: -1 }).valid).toBe(true)
  const stages = oxdnaProductionStagePlan(values)
  expect(stages).toHaveLength(13)
  expect(stages.every(stage => stage.steps === 123000 && stage.purpose === 'Fixed temperature dwell')).toBe(true)
})
