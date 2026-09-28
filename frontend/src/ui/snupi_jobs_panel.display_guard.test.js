// @vitest-environment jsdom
//
// Integration test for the Coarse/Fine launch guard: a rapid double-click on a
// launch button must create exactly ONE SNUPI FEM job (the reported bug spawned a
// duplicate job entry that crashed).  Mounts the real factory against a minimal DOM
// with the api + side modules mocked.
import { describe, it, expect, vi, beforeEach } from 'vitest'

// confirmNoConcurrentJob only knows MD/oxDNA jobs — for the FEM it always resolves
// true, which is exactly why the panel needs its own guard.  Make it async so the
// second click fires while the first is still awaiting it (the race window).
vi.mock('./job_activity.js', () => ({
  confirmNoConcurrentJob: vi.fn(async () => true),
}))
vi.mock('./toast.js', () => ({ showToast: vi.fn() }))
vi.mock('./md_jobs_panel.js', () => ({
  filterJobsForPart: (jobs, workspacePath) => workspacePath
    ? jobs.filter((job) => job.design_source_path === workspacePath)
    : jobs,
}))
vi.mock('./snupi_metrics_card.js', () => ({
  initSnupiMetricsCard: () => ({ sync() {}, refresh() {} }),
}))

let _jobsOnServer = []
const createSnupiJob = vi.fn(async (body) => {
  const job = { job_id: `job${_jobsOnServer.length + 1}`, status: 'running', nonlinear: !!body.nonlinear }
  _jobsOnServer.push(job)
  return job
})
vi.mock('../api/client.js', () => ({
  createSnupiJob: (...a) => createSnupiJob(...a),
  listSnupiJobs: async () => _jobsOnServer,
  getSnupiJob: async id => _jobsOnServer.find(j => j.job_id === id),
  getSnupiProgress: async () => ({ overall: 0.5 }),
  lastErrorMessage: () => '',
  stopSnupiJob: async () => ({}),
  deleteSnupiJob: async () => ({ ok: true }),
  startSnupiAutorefine: async () => null,
  stopSnupiAutorefine: async () => ({}),
  getSnupiAutorefine: async () => null,
  applySnupiAutorefine: async () => null,
  syncDesignResponse: () => {},
}))

// The panel needs these ids present (panel/heading/body or it early-returns).
function mountDom() {
  document.body.innerHTML = `
    <div id="snupi-jobs-panel">
      <div id="snupi-jobs-heading"></div>
      <div id="snupi-jobs-body">
        <button id="snupi-jobs-coarse-btn">Coarse</button>
        <button id="snupi-jobs-fine-btn">Fine</button>
        <input id="snupi-jobs-n-steps" value="20">
        <input id="snupi-jobs-with-rmsf" type="checkbox" checked>
        <div id="snupi-jobs-list"></div>
        <div id="snupi-jobs-detail"></div>
        <label><input class="snupi-display-mode" type="radio" name="snupi-mode" value="off" checked>Off</label>
        <label><input class="snupi-display-mode" type="radio" name="snupi-mode" value="deform">Predicted shape</label>
        <label><input class="snupi-display-mode" type="radio" name="snupi-mode" value="flex">Flexibility</label>
        <label><input class="snupi-display-mode" type="radio" name="snupi-mode" value="deviation">Deviation</label>
      </div>
    </div>`
}

async function flush() { await new Promise((r) => setTimeout(r, 0)) }

it('uses the job snapshot when displaying a current assembly result', async () => {
  const { store } = await import('../state/store.js')
  const { initSnupiJobsPanel } = await import('./snupi_jobs_panel.js')
  mountDom()
  _jobsOnServer = [{ job_id: 'assembly-display', status: 'completed', out_of_date: false, n_nucleotides: 424144 }]
  const display = { showDeform: vi.fn(async () => ({ ok: true })), deformActive: () => false, mode: () => 'deform' }
  const panel = initSnupiJobsPanel({ snupiDisplay: display })
  store.setState({ assemblyActive: true })
  try {
    await panel.selectJob('assembly-display')
    document.querySelector('.snupi-display-mode[value="deform"]').click()
    await flush()
    expect(display.showDeform).toHaveBeenCalledWith('assembly-display', expect.any(Function), { reuseLiveGeometry: false, nNucleotides: 424144 })
  } finally { store.setState({ assemblyActive: false }) }
})

it('a stale mode failure cannot turn off a newer successful visualization', async () => {
  const { initSnupiJobsPanel } = await import('./snupi_jobs_panel.js')
  mountDom()
  _jobsOnServer = [{ job_id: 'race', status: 'completed', rmsf_max_nm: 1, n_nucleotides: 100000 }]
  let reject, mode = null
  const display = {
    showDeform: () => new Promise((_, r) => { reject = r }),
    showFlex: async () => { mode = 'flex'; return { ok: true } },
    stopDeform: vi.fn(() => { mode = null }),
    deformActive: () => !!mode, mode: () => mode,
  }
  const panel = initSnupiJobsPanel({ snupiDisplay: display })
  await panel.selectJob('race')
  display.stopDeform.mockClear()
  document.querySelector('.snupi-display-mode[value="deform"]').click()
  document.querySelector('.snupi-display-mode[value="flex"]').click()
  await flush()
  reject(new DOMException('Aborted', 'AbortError'))
  await flush()
  expect(mode).toBe('flex')
  expect(document.querySelector('.snupi-display-mode[value="flex"]').checked).toBe(true)
  expect(display.stopDeform).not.toHaveBeenCalled()
})
it('leaving the engine stops hidden playback and resets its mode controls', async () => {
  const { initSnupiJobsPanel } = await import('./snupi_jobs_panel.js')
  mountDom()
  let active = true
  const display = { deformActive: () => active, mode: () => active ? 'trajectory' : null,
    stopAndRestore: vi.fn(() => { active = false }) }
  initSnupiJobsPanel({ snupiDisplay: display })
  window.dispatchEvent(new CustomEvent('nadoc:simulation-engine', { detail: { engine: 'cando' } }))
  expect(display.stopAndRestore).toHaveBeenCalledTimes(1)
  expect(document.querySelector('.snupi-display-mode[value="off"]').checked).toBe(true)
})
