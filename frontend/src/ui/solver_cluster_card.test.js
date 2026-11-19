// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from 'vitest'
import { standardizeSimulationCardOrder } from './simulation_card_order.js'
import { initSolverClusterCard, solverExecutionPayload, remoteSolverStatus } from './solver_cluster_card.js'
vi.mock('./solver_runpod_card.js', () => ({ initSolverRunpodCard: () => ({ refresh() {}, showJob() {}, applySettings() {}, dispose() {}, payload: () => ({ execution_target: 'runpod' }) }) }))
vi.mock('./cluster_availability.js', () => ({ initClusterAvailability: () => ({ dispose() {} }) }))
vi.mock('./cluster_connection.js', () => ({ initClusterConnection: () => ({ getState: () => 'connected', refresh: vi.fn(), dispose: vi.fn() }) }))
afterEach(() => { document.body.replaceChildren(); localStorage.clear() })
it('defaults to local and validates remote requirements', () => {
  expect(solverExecutionPayload('local')).toEqual({ execution_target: 'local' })
  expect(() => solverExecutionPayload('alpine', {})).toThrow('Python')
  expect(() => solverExecutionPayload('alpine', { python: '/env/python', cores: 0 })).toThrow('positive')
})
it('reports scheduler evidence and download failures without claiming completion', () => {
  expect(remoteSolverStatus({ execution_target: 'alpine', remote: { slurm_job_id: '123', scheduler_state: 'TIMEOUT' } })).toContain('123 · TIMEOUT')
  expect(remoteSolverStatus({ execution_target: 'alpine', remote: { downloading: true } })).toContain('Downloading')
  expect(remoteSolverStatus({ execution_target: 'local' })).toBe('')
})
describe.each(['snupi', 'mrdna'])('%s shared card', engine => {
  it.each(['part', 'assembly'])('preserves the same execution contract in %s host', host => {
    const mount = document.createElement('div'); mount.dataset.host = host; document.body.append(mount)
    const changed = vi.fn()
    const card = initSolverClusterCard({ mount, engine, onChange: changed })
    const jobs = document.createElement('div'); jobs.className = 'ox-card'
    jobs.innerHTML = '<div class="ox-card__header"><span class="ox-card__title">Jobs</span></div>'
    document.body.append(jobs)
    expect(standardizeSimulationCardOrder(document.body)).toEqual(['Jobs', 'Clusters'])
    expect(mount.querySelector('.ox-card__chevron')).not.toBeNull()
    expect(card.payload()).toEqual({ execution_target: 'local' })
    const target = mount.querySelector(`#${engine}-run-target-alpine`)
    target.checked = true; target.dispatchEvent(new Event('change'))
    mount.querySelector(`#${engine}-cluster-python`).value = '/remote/venv/bin/python'
    if (engine === 'mrdna') mount.querySelector(`#${engine}-cluster-arbd`).value = '/remote/bin/arbd'
    expect(card.payload()).toMatchObject({ execution_target: 'alpine', cluster_settings: { cores: 8, python: '/remote/venv/bin/python' } })
    expect(changed).toHaveBeenCalled()
    card.showJob({ execution_target: 'alpine', remote: { scheduler_state: 'PENDING' } })
    expect(mount.textContent).toContain('PENDING')
    mount.querySelector('.ox-card__header').click()
    expect(mount.querySelector('.ox-card__header').getAttribute('aria-expanded')).toBe('false')
    card.dispose(); expect(mount.childElementCount).toBe(0)
  })
})

vi.mock('../api/client.js', () => ({
  estimateSolverResources: vi.fn(async () => ({ ram_gib: 2, vram_gib: 0, disk_gib: 1, min_ram_gib: 3, min_vram_gb: 0,
    alpine: [{ id: 'acpu', max_ram_gib: 256, max_cores: 64, mem_per_core_gb: 4, qos: [{ name: 'cpu-normal', minutes: 120 }] }] })),
  lastErrorMessage: () => '',
  getClusterAvailability: vi.fn(async () => ({ partitions: [] })),
}))
it('prepares a remote allocation from current solver options and cancels without a payload', async () => {
  const { estimateSolverResources } = await import('../api/client.js')
  const mount = document.createElement('div'); document.body.append(mount)
  const card = initSolverClusterCard({ mount, engine: 'snupi' })
  expect(await card.prepareLaunch({})).toEqual({ execution_target: 'local' })
  mount.querySelector('#snupi-run-target-alpine').checked = true
  const options = { dynamics: true, hydrodynamics: true, hydro_coarse_bp: 8 }
  const pending = card.prepareLaunch(options)
  await vi.waitFor(() => expect(document.querySelector('[role="dialog"]')).not.toBeNull())
  expect(estimateSolverResources).toHaveBeenCalledWith('snupi', options)
  card.dispose()
  expect(await pending).toBeNull()
})

it('joins whole-GPU availability to the wizard and refreshes it explicitly', async () => {
  const { estimateSolverResources, getClusterAvailability } = await import('../api/client.js')
  estimateSolverResources.mockResolvedValueOnce({
    ram_gib: 2, vram_gib: 0, disk_gib: 1, min_ram_gib: 3, min_vram_gb: 0,
    runtime: { seconds: 3600 },
    alpine: [{ id: 'aa100', gres_type: 'a100', cuda: true, vram_gb: 40, max_ram_gib: 256, max_cores: 64,
      mem_per_core_gb: 4, qos: [{ name: 'gpu-normal', minutes: 120 }] }],
  })
  getClusterAvailability.mockResolvedValue({
    partitions: [{ partition: 'aa100', gpus_free: 0, gpus_total: 4, wait_min: 40,
      gpu_resources: [
        { gres_type: 'a100', mig: false, gpus_free: 1, gpus_total: 2, wait_min: 12 },
        { gres_type: '1g', mig: true, gpus_free: 6, gpus_total: 8, wait_min: 0 },
      ] }],
  })
  const mount = document.createElement('div'); document.body.append(mount)
  const card = initSolverClusterCard({ mount, engine: 'snupi' })
  mount.querySelector('#snupi-run-target-alpine').checked = true
  const pending = card.prepareLaunch({})
  await vi.waitFor(() => expect(document.querySelector('[role=dialog]')).not.toBeNull())
  const dialog = document.querySelector('[role=dialog]')
  expect(dialog.textContent).toContain('1 / 2 GPUs free')
  expect(dialog.textContent).toContain('12 min')
  expect(dialog.textContent).not.toContain('6 / 8 GPUs free')
  expect(getClusterAvailability).toHaveBeenLastCalledWith({ force: false })
  ;[...dialog.querySelectorAll('button')].find(b => b.textContent === 'Re-check availability').click()
  await vi.waitFor(() => expect(getClusterAvailability).toHaveBeenLastCalledWith({ force: true }))
  card.dispose(); expect(await pending).toBeNull()
})

it.each(['snupi', 'mrdna'])('%s selects the job provider and preserves edits across polls', engine => {
  const mount = document.createElement('div'); document.body.append(mount)
  const card = initSolverClusterCard({ mount, engine })
  const job = { job_id: 'remote', execution_target: 'runpod', status: 'running', remote: { pod_id: 'pod123' } }
  card.showJob(job)
  expect(mount.querySelector(`#${engine}-run-target-runpod`).checked).toBe(true)
  expect(mount.querySelector(`#${engine}-jobs-runpod-pane`).hidden).toBe(false)
  expect(mount.textContent).toContain('Pod pod123')
  mount.querySelector(`#${engine}-run-target-local`).click()
  card.showJob(job)
  expect(mount.querySelector(`#${engine}-run-target-local`).checked).toBe(true)
  card.showJob({ job_id: 'alpine', execution_target: 'alpine', remote: { settings: { cores: 16 } } })
  expect(mount.querySelector(`#${engine}-run-target-alpine`).checked).toBe(true)
  expect(mount.querySelector(`#${engine}-cluster-cores`).value).toBe('16')
  card.showJob({ job_id: 'local' })
  expect(mount.querySelector(`#${engine}-run-target-local`).checked).toBe(true)
  card.dispose()
})
