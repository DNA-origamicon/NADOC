// @vitest-environment jsdom
//
// Integration test for the Coarse/Fine launch guard: a rapid double-click on a
// launch button must create exactly ONE CanDo FEM job (the reported bug spawned a
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
vi.mock('./cando_metrics_card.js', () => ({
  initCandoMetricsCard: () => ({ sync() {}, refresh() {} }),
}))

let _jobsOnServer = []
const createCandoJob = vi.fn(async (body) => {
  const job = { job_id: `job${_jobsOnServer.length + 1}`, status: 'running', nonlinear: !!body.nonlinear }
  _jobsOnServer.push(job)
  return job
})
vi.mock('../api/client.js', () => ({
  createCandoJob: (...a) => createCandoJob(...a),
  listCandoJobs: async () => _jobsOnServer,
  getCandoProgress: async () => ({ overall: 0.5 }),
  lastErrorMessage: () => '',
  stopCandoJob: async () => ({}),
  deleteCandoJob: async () => ({ ok: true }),
  startCandoAutorefine: async () => null,
  stopCandoAutorefine: async () => ({}),
  getCandoAutorefine: async () => null,
  applyCandoAutorefine: async () => null,
  syncDesignResponse: () => {},
}))

// The panel needs these ids present (panel/heading/body or it early-returns).
function mountDom() {
  document.body.innerHTML = `
    <div id="cando-jobs-panel">
      <div id="cando-jobs-heading"></div>
      <div id="cando-jobs-body">
        <button id="cando-jobs-coarse-btn">Coarse</button>
        <button id="cando-jobs-fine-btn">Fine</button>
        <input id="cando-jobs-n-steps" value="20">
        <input id="cando-jobs-with-rmsf" type="checkbox" checked>
        <div id="cando-jobs-list"></div>
        <div id="cando-jobs-detail"></div>
        <label><input class="cando-display-mode" type="radio" name="cando-mode" value="off" checked>Off</label>
        <label><input class="cando-display-mode" type="radio" name="cando-mode" value="deform">Predicted shape</label>
        <label><input class="cando-display-mode" type="radio" name="cando-mode" value="flex">Flexibility</label>
        <label><input class="cando-display-mode" type="radio" name="cando-mode" value="deviation">Deviation</label>
      </div>
    </div>`
}

async function flush() { await new Promise((r) => setTimeout(r, 0)) }

describe('CanDo launch guard (double-click)', () => {
  let initCandoJobsPanel
  beforeEach(async () => {
    _jobsOnServer = []
    createCandoJob.mockClear()
    mountDom()
    // Import after the DOM + mocks are in place.
    ;({ initCandoJobsPanel } = await import('./cando_jobs_panel.js'))
  })

  it('creates exactly one job when the Coarse button is clicked twice rapidly', async () => {
    initCandoJobsPanel({ candoDisplay: null, getWorkspacePath: () => null })
    // Panel starts collapsed → open it so the launch handlers are live.
    document.getElementById('cando-jobs-heading').click()
    await flush()

    const coarse = document.getElementById('cando-jobs-coarse-btn')
    coarse.click()   // launch #1 — enters, sets guard, awaits confirm
    coarse.click()   // launch #2 — must bail on the synchronous guard
    await flush(); await flush()

    expect(createCandoJob).toHaveBeenCalledTimes(1)
    // Button stays disabled while the created job is still running.
    expect(coarse.disabled).toBe(true)
  })

  it('re-enables the buttons once the job is no longer active', async () => {
    const panel = initCandoJobsPanel({ candoDisplay: null, getWorkspacePath: () => null })
    document.getElementById('cando-jobs-heading').click()
    await flush()

    const coarse = document.getElementById('cando-jobs-coarse-btn')
    coarse.click()
    await flush(); await flush()
    expect(coarse.disabled).toBe(true)   // stays locked while the job runs

    // Job finishes; a poll (refresh) sees it completed and re-enables the buttons.
    _jobsOnServer.forEach((j) => { j.status = 'completed' })
    await panel.refresh()
    expect(coarse.disabled).toBe(false)

    // A fresh launch is now allowed (guard released).
    coarse.click()
    await flush(); await flush()
    expect(createCandoJob).toHaveBeenCalledTimes(2)
  })

  it('enables visualizations when the unified list selects a completed assembly job', async () => {
    _jobsOnServer = [{
      job_id: 'assembly-job', status: 'completed', nonlinear: false,
      design_name: 'BigO-poly', design_source_path: null, rmsf_max_nm: 0.7,
    }]
    const candoDisplay = { deformActive: () => false, mode: () => null }
    const panel = initCandoJobsPanel({
      candoDisplay,
      getWorkspacePath: () => '/designs/BigO-poly.nass',
    })

    await panel.selectJob('assembly-job')

    expect(panel.getSelectedJob()?.job_id).toBe('assembly-job')
    for (const radio of document.querySelectorAll('.cando-display-mode')) {
      expect(radio.disabled).toBe(false)
    }
  })
})

it('cleans up a failed assembly preparation and allows retry with a CPU launch', async () => {
  const { confirmNoConcurrentJob } = await import('./job_activity.js')
  const { showToast } = await import('./toast.js')
  const { initCandoJobsPanel } = await import('./cando_jobs_panel.js')
  mountDom()
  _jobsOnServer = []
  createCandoJob.mockRejectedValueOnce(new Error('Missing assembly source'))
  const events = []
  const listener = e => events.push(e.detail)
  window.addEventListener('nadoc:sim-jobs-changed', listener)
  const panel = initCandoJobsPanel({ candoDisplay: null, getWorkspacePath: () => null })
  try {
    const coarse = document.getElementById('cando-jobs-coarse-btn')
    coarse.click()
    await flush(); await flush()
    expect(showToast).toHaveBeenCalledWith('Missing assembly source', { severity: 'error' })
    expect(confirmNoConcurrentJob).toHaveBeenCalledWith({ usesGpu: false })
    expect(events.some(event => event?.removeJobId?.startsWith('preparing-'))).toBe(true)
    expect(coarse.disabled).toBe(false)
    expect(panel.getSelectedJob()).toBeFalsy()
  } finally {
    window.removeEventListener('nadoc:sim-jobs-changed', listener)
  }
})

it('uses the job snapshot when displaying a current assembly result', async () => {
  const { store } = await import('../state/store.js')
  const { initCandoJobsPanel } = await import('./cando_jobs_panel.js')
  mountDom()
  _jobsOnServer = [{ job_id: 'assembly-display', status: 'completed', out_of_date: false, n_nucleotides: 424144 }]
  const display = { showDeform: vi.fn(async () => ({ ok: true })), deformActive: () => false, mode: () => 'deform' }
  const panel = initCandoJobsPanel({ candoDisplay: display })
  store.setState({ assemblyActive: true })
  try {
    await panel.selectJob('assembly-display')
    document.querySelector('.cando-display-mode[value="deform"]').click()
    await flush()
    expect(display.showDeform).toHaveBeenCalledWith('assembly-display', expect.any(Function), { reuseLiveGeometry: false, nNucleotides: 424144 })
  } finally { store.setState({ assemblyActive: false }) }
})

it('a stale mode failure cannot turn off a newer successful visualization', async () => {
  const { initCandoJobsPanel } = await import('./cando_jobs_panel.js')
  mountDom()
  _jobsOnServer = [{ job_id: 'race', status: 'completed', rmsf_max_nm: 1, n_nucleotides: 100000 }]
  let reject, mode = null
  const display = {
    showDeform: () => new Promise((_, r) => { reject = r }),
    showFlex: async () => { mode = 'flex'; return { ok: true } },
    stopDeform: vi.fn(() => { mode = null }),
    deformActive: () => !!mode, mode: () => mode,
  }
  const panel = initCandoJobsPanel({ candoDisplay: display })
  await panel.selectJob('race')
  display.stopDeform.mockClear()
  document.querySelector('.cando-display-mode[value="deform"]').click()
  document.querySelector('.cando-display-mode[value="flex"]').click()
  await flush()
  reject(new DOMException('Aborted', 'AbortError'))
  await flush()
  expect(mode).toBe('flex')
  expect(document.querySelector('.cando-display-mode[value="flex"]').checked).toBe(true)
  expect(display.stopDeform).not.toHaveBeenCalled()
})
