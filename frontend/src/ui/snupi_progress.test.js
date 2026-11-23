import { describe, it, expect } from 'vitest'
import { snupiDynamicsProgress } from './snupi_progress.js'
import { masterProgressPct, masterStepText } from './simulate_jobs.js'
const base = { engine: 'snupi', dynamics: true, status: 'running', n_steps: 20 }
describe('actual Langevin progress', () => {
  it('does not use static load steps or weighted mesh progress', () => {
    expect(snupiDynamicsProgress({ ...base, progress_fraction: .12 }).text).toContain('60,000 steps planned')
    expect(masterProgressPct({ ...base, progress_fraction: .12 })).toBe(0)
  })
  it('uses exact counters in both the bar and readout', () => {
    const node = { ...base, current_step: 15000, total_steps: 60000, progress_fraction: .325 }
    expect(masterProgressPct(node)).toBe(25)
    expect(masterStepText(node)).toBe('25% dynamics · 15,000 / 60,000 steps · 45,000 left')
  })
  it('shows pending setup and an indeterminate bar', () => {
    const p = snupiDynamicsProgress({ ...base, current_step: 0, progress_indeterminate: true })
    expect(p.indeterminate).toBe(true)
    expect(p.text).toBe('Dynamics pending · 60,000 steps planned')
  })
  it('retains last measured progress through disconnects and resets on retry', () => {
    const node = { ...base, current_step: 500, total_steps: 60000, attempt: 1, progress_last_known: true }
    expect(masterStepText(node)).toContain('0.8% dynamics · 500 / 60,000')
    expect(masterStepText(node)).toContain('retry 1 · last known')
  })
  it('distinguishes finished integration from job completion', () => {
    expect(snupiDynamicsProgress({ ...base, current_step: 60000 }).fraction).toBe(1)
    expect(snupiDynamicsProgress({ ...base, status: 'completed' }).text).toContain('100% dynamics')
    expect(snupiDynamicsProgress({ ...base, dynamics: false })).toBeNull()
  })
})
