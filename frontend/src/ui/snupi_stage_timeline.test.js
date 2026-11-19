// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'
import { snupiDynamicsStages, renderSnupiDynamicsTimeline } from './snupi_stage_timeline.js'
const base = { engine: 'snupi', dynamics: true, status: 'running', execution_target: 'runpod' }
const states = node => Object.fromEntries(snupiDynamicsStages(node).map(s => [s.id, s.status]))
describe('SNUPI dynamics stage evidence', () => {
  it('shows preparation before integration from the current worker phase', () => {
    expect(states({ ...base, phase: 'RunPod · Calculating stable dynamics timestep' })).toEqual({
      deployment: 'done', mesh: 'done', stiffness: 'done', timestep: 'running', integration: 'pending', analysis: 'pending', download: 'pending',
    })
  })
  it('includes hydrodynamic preparation only when requested', () => {
    const s = states({ ...base, hydrodynamics: true, phase: 'Alpine · building hydrodynamic friction' })
    expect(s.timestep).toBe('done'); expect(s.friction).toBe('running'); expect(s.integration).toBe('pending')
    expect(states({ ...base, phase: 'mesh' }).friction).toBeUndefined()
  })
  it('treats steps as integration and keeps analysis pending at the last step until reported', () => {
    const rows = snupiDynamicsStages({ ...base, phase: 'RunPod · trajectory', current_step: 60000, total_steps: 60000, n_steps: 20, attempt: 1 })
    expect(rows.find(s => s.id === 'integration')).toMatchObject({ status: 'running', detail: '60,000 / 60,000 steps · retry 1' })
    expect(rows.find(s => s.id === 'analysis').status).toBe('pending')
    expect(states({ ...base, phase: 'Analyzing dynamics trajectory' }).analysis).toBe('running')
  })
  it('distinguishes transfer, completion and local jobs', () => {
    expect(states({ ...base, remote: { downloading: true } }).download).toBe('running')
    expect(Object.values(states({ ...base, status: 'completed' })).every(s => s === 'done')).toBe(true)
    const local = states({ ...base, execution_target: 'local', phase: 'trajectory' })
    expect(local.deployment).toBeUndefined(); expect(local.download).toBeUndefined()
  })
  it('does not invent progress for missing telemetry, terminal jobs, or stale samples', () => {
    expect(states(base).integration).toBe('pending')
    expect(states({ ...base, status: 'queued' }).deployment).toBe('queued')
    expect(states({ ...base, status: 'failed', phase: 'Calculating stable dynamics timestep' }).timestep).toBe('failed')
    expect(states({ ...base, status: 'stopped', phase: 'trajectory' }).integration).toBe('stopped')
    expect(states({ ...base, phase: 'trajectory', progress_last_known: true }).integration).toBe('last-known')
    expect(snupiDynamicsStages({ ...base, dynamics: false })).toBeNull()
  })
  it('renders accessible themed rows, updates stages, and clears old integration counters', () => {
    const el = document.createElement('div')
    renderSnupiDynamicsTimeline(el, { ...base, phase: 'trajectory', current_step: 30000, total_steps: 60000 })
    expect(el.querySelector('[data-stage="integration"]').textContent).toContain('30,000 / 60,000 steps')
    expect(el.querySelector('[aria-current="step"]').dataset.stage).toBe('integration')
    renderSnupiDynamicsTimeline(el, { ...base, status: 'completed' })
    expect(el.querySelector('[aria-current]')).toBeNull()
    expect(el.textContent).not.toContain('30,000')
    expect(el.textContent).toContain('Download results')
  })
})
