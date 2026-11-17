import { describe, it, expect, vi } from 'vitest'
import { thermalSkipAction, skipThermalStage } from './oxdna_thermal_skip.js'

const job = { job_id: 'tm', engine: 'oxdna', status: 'running', current_stage_idx: 0,
  run_config: { thermal_ramp: {} }, stages: [{ name: '1_thermal' }, { name: '2_thermal' }] }

describe('skip thermal stage', () => {
  it('uses the current temperature and disables final/ordinary/remote jobs', () => {
    expect(thermalSkipAction(job)).toMatchObject({ enabled: true, stage: '1_thermal' })
    expect(thermalSkipAction({ ...job, current_stage_idx: 1 }).enabled).toBe(false)
    expect(thermalSkipAction({ ...job, status: 'completed' }).enabled).toBe(false)
    expect(thermalSkipAction({ ...job, execution_target: 'runpod' }).enabled).toBe(false)
    expect(thermalSkipAction({ ...job, run_config: {} })).toBeNull()
  })
  it('sends an expected-stage guard and refreshes after acceptance', async () => {
    const api = { skipOxdnaStage: vi.fn().mockResolvedValue({ ok: true }) }
    const refresh = vi.fn(), toast = vi.fn()
    await skipThermalStage(job, { api, refresh, toast })
    expect(api.skipOxdnaStage).toHaveBeenCalledWith('tm', { expected_stage: '1_thermal' })
    expect(refresh).toHaveBeenCalledOnce()
    api.skipOxdnaStage.mockResolvedValue(null)
    await skipThermalStage(job, { api, refresh, toast })
    expect(toast).toHaveBeenLastCalledWith(expect.stringContaining('Could not skip'), { severity: 'error' })
  })
})
