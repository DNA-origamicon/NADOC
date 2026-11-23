// @vitest-environment jsdom
import { it, expect, vi, afterEach } from 'vitest'
import { initSolverRunpodCard } from './solver_runpod_card.js'
vi.mock('./runpod_setup.js', () => ({ initRunpodSetup: () => ({ dispose() {} }) }))
vi.mock('./runpod_status.js', () => ({ initRunpodStatus: () => ({ refresh() {}, refreshSession() {}, refreshBilling() {} }) }))
afterEach(() => document.body.replaceChildren())
it('requires a live GPU selection and submits budget, host RAM and actual quote', async () => {
  const mount = document.createElement('div'); document.body.append(mount)
  const fetchImpl = vi.fn(async () => ({ ok: true, json: async () => ({ gpus: [{ id: 'gpu', display: 'Test GPU', vram_gb: 24, on_demand: .5 }] }) }))
  const card = initSolverRunpodCard({ mount, engine: 'snupi', fetchImpl })
  expect(() => card.payload()).toThrow('choose a GPU')
  mount.querySelector('button').click()
  await vi.waitFor(() => expect(mount.querySelector('.runpod-gpu-row')).not.toBeNull())
  mount.querySelector('.runpod-gpu-row').click()
  expect(card.payload()).toMatchObject({ execution_target: 'runpod', runpod_settings: { quoted_rate: .5, budget_usd: 5, mem_gb: 64 } })
  expect(mount.textContent).not.toContain('ns/day')
  mount.querySelector('#snupi-runpod-budget_usd').value = '-1'
  expect(() => card.payload()).toThrow('positive')
  card.applySettings({ gpu_id: 'larger', quoted_rate: 1, budget_usd: 10, mem_gb: 128 })
  expect(mount.querySelector('.runpod-gpu-row')).toBeNull()
  expect(card.values()).toMatchObject({ gpu_id: 'larger', mem_gb: 128, budget_usd: 10 })
  expect(card.payload().runpod_settings).toMatchObject({ gpu_id: 'larger', quoted_rate: 1, mem_gb: 128 })
  card.dispose(); expect(mount.childElementCount).toBe(0)
})

it('shows selected job resources and clears stale details', () => {
  const mount = document.createElement('div'); document.body.append(mount)
  const card = initSolverRunpodCard({ mount, engine: 'snupi' })
  card.showJob({ job_id: 'job1', status: 'running', remote: { pod_id: 'pod1', settings: { gpu_id: 'RTX 4090', mem_gb: 75, cores: 8, quoted_rate: .89, budget_usd: 5 } } })
  const info = mount.querySelector('#snupi-runpod-selected-job')
  expect(info.hidden).toBe(false)
  expect(info.textContent).toContain('RTX 4090')
  expect(info.textContent).toContain('75 GiB')
  expect(info.textContent).toContain('pod1')
  card.showJob(null)
  expect(info.hidden).toBe(true)
  expect(info.textContent).toBe('')
  card.dispose()
})
