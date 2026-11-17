// @vitest-environment jsdom
import { expect, it, vi } from 'vitest'
import { isThermalRun, thermalRunNumbers, thermalRunSteps, thermalRunSignature } from './oxdna_thermal_job.js'
import { buildJobListModel, jobListSignature } from './jobs_panel_model.js'
import { renderJobList } from './jobs_panel_render.js'

const job = (overrides = {}) => ({ job_id: 'tm', parent_job_id: 'relax', engine: 'oxdna',
  design_source_path: 'duplex.nadoc', created_at: 2, status: 'running', current_stage_idx: 1,
  run_config: { thermal_ramp: { start_c: 25, end_c: 36, step_c: 5 } },
  stages: ['done', 'running', 'pending', 'pending'].map((status, i) => ({ name: `${i + 1}_thermal`, status, steps: 1000000 })), ...overrides })
const ctx = { engine: 'oxdna', hierarchical: true, displayName: () => 'relax 1', childLabel: (_, i) => `Run ${i}`, colors: { dim: '#888', warn: '#f90' } }

it('uses production run numbering per design, including orphaned thermal runs', () => {
  const jobs = [job({ job_id: 'second', created_at: 3 }), job({ job_id: 'first', created_at: 1 }),
    job({ job_id: 'ordinary', run_config: {} }), job({ job_id: 'other', design_source_path: 'other.nadoc' })]
  const numbers = thermalRunNumbers(jobs)
  expect([...numbers]).toEqual([['first', 1], ['other', 1], ['second', 3]])
  expect(isThermalRun({ engine: 'namd', run_config: job().run_config })).toBe(false)
  const rows = buildJobListModel([jobs[0]], { ...ctx, thermalNumbers: numbers }).rows
  expect(rows[0].label).toBe('Tm Run 3')
  expect(rows[0].thermalSteps).toHaveLength(4)
})

it('shows recorded statuses and the heating/cooling endpoint without inventing child jobs', () => {
  const steps = thermalRunSteps(job())
  expect(steps.map(s => s.temperature)).toEqual(['25 °C', '30 °C', '35 °C', '36 °C'])
  expect(steps.map(s => s.status)).toEqual(['completed', 'running', 'waiting', 'waiting'])
  const cooling = job({ run_config: { thermal_ramp: { start_c: 36, end_c: 25, step_c: 5 } } })
  expect(thermalRunSteps(cooling).map(s => s.temperature)).toEqual(['36 °C', '31 °C', '26 °C', '25 °C'])
  expect(thermalRunSteps({ run_config: {} })).toBeNull()
})

it('shows stopped and failed current stages without mislabelling waiting stages', () => {
  expect(thermalRunSteps(job({ status: 'stopped' })).map(s => s.status)).toEqual(['completed', 'stopped', 'waiting', 'waiting'])
  expect(thermalRunSteps(job({ status: 'failed' }))[1].status).toBe('failed')
  const extending = job(); extending.stages[1] = { ...extending.stages[1], status: 'pending', started_at: 1 }
  expect(thermalRunSteps(extending)[1].status).toBe('running')
})

it('uses recorded actual temperature and excludes later ordinary production', () => {
  const j = job(); j.run_config.thermal_progress = { '1_thermal': { temperature: '300K' } }
  j.stages.push({ name: '5_production', status: 'pending' })
  expect(thermalRunSteps(j)).toHaveLength(4)
  expect(thermalRunSteps(j)[0].temperature).toBe('26.85 °C')
})

it('invalidates list rendering when a temperature completes while the job stays running', () => {
  const before = job(), after = structuredClone(before)
  after.stages[1].status = 'done'; after.stages[2].status = 'running'; after.current_stage_idx = 2
  expect(thermalRunSignature(before)).not.toBe(thermalRunSignature(after))
  expect(jobListSignature([before], ctx)).not.toBe(jobListSignature([after], ctx))
})

it('preserves run indicator suffixes in thermal labels', () => {
  const rows = buildJobListModel([job()], { ...ctx, childLabel: (_, i) => `Run ${i} [A]` }).rows
  expect(rows[0].label).toBe('Tm Run 1 [A]')
})

it('expands without selecting the job and retains expansion through polling', () => {
  const list = document.createElement('div'), onClick = vi.fn()
  const before = job()
  renderJobList(list, buildJobListModel([before], ctx), { onClick })
  const toggle = list.querySelector('button')
  expect(toggle.getAttribute('aria-expanded')).toBe('false')
  toggle.click()
  expect(onClick).not.toHaveBeenCalled()
  expect(list.querySelector('.thermal-job-details').hidden).toBe(false)
  expect(list.querySelector('ol').textContent).toContain('30C - Run 1 Running')
  const after = structuredClone(before); after.stages[1].status = 'done'; after.stages[2].status = 'running'; after.current_stage_idx = 2
  renderJobList(list, buildJobListModel([after], ctx), { onClick })
  expect(list.querySelector('button').getAttribute('aria-expanded')).toBe('true')
  expect(list.querySelector('.thermal-job-summary').textContent).toBe('2 / 4 temperature steps completed')
  expect(list.querySelector('[data-thermal-stage="3_thermal"]').dataset.status).toBe('running')
  list.querySelector('[data-job-id="tm"]').click()
  expect(onClick).toHaveBeenCalledWith('tm')
  list.querySelector('button').click()
  expect(list.querySelector('.thermal-job-details').hidden).toBe(true)
})

it('routes every child context menu to its parent and labels skipped temperatures honestly', () => {
  const list = document.createElement('div'), onContextMenu = vi.fn()
  const value = job()
  value.stages[0].status = 'skipped'
  renderJobList(list, buildJobListModel([value], ctx), { onContextMenu })
  expect(list.querySelector('[data-thermal-stage="1_thermal"]').textContent).toContain('Skipped')
  for (const child of list.querySelectorAll('[data-thermal-stage]')) {
    child.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true }))
    expect(onContextMenu).toHaveBeenLastCalledWith('tm', expect.any(MouseEvent))
  }
  expect(onContextMenu).toHaveBeenCalledTimes(4)
})
