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
vi.mock('./md_jobs_panel.js', () => ({ filterJobsForPart: (jobs) => jobs }))
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
})
