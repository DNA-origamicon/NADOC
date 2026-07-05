// @vitest-environment jsdom
//
// Integration test for the auto-applying autorefine JOB flow (repointed button): clicking
// Autorefine creates a kind=autorefine CanDo job that refines + auto-applies the loop/skips
// (feature log) server-side, then completes as a normal job.  The panel must, on completion,
// show what was applied (NOT ask for a manual Apply), refresh the design (getDesign), and select
// the job so its display modes are available.
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('./job_activity.js', () => ({ confirmNoConcurrentJob: vi.fn(async () => true) }))
vi.mock('./toast.js', () => ({ showToast: vi.fn() }))
vi.mock('./md_jobs_panel.js', () => ({ filterJobsForPart: (jobs) => jobs }))
vi.mock('./cando_metrics_card.js', () => ({
  initCandoMetricsCard: () => ({ sync() {}, refresh() {} }),
}))

// A completed autorefine job — the shape the backend returns for a square strut (verified
// headlessly: applied 26 marks, period 36, RMSD 0.72→0.19).
const DONE_JOB = {
  job_id: 'job1', kind: 'autorefine', status: 'completed',
  refine_applied: true, refine_n_marks: 26, refine_period: 36,
  refine_before_rmsd: 0.7154, refine_after_rmsd: 0.1919,
  refine_note: 'Applied 26 marks (period 36) · deviation 0.72→0.19 nm',
}
const createCandoJob = vi.fn(async () => ({ job_id: 'job1', status: 'queued', kind: 'autorefine' }))
const getCandoJob = vi.fn(async () => DONE_JOB)
const getDesign = vi.fn(async () => ({}))
vi.mock('../api/client.js', () => ({
  listCandoJobs: async () => [DONE_JOB],
  lastErrorMessage: () => '',
  createCandoJob: (...a) => createCandoJob(...a),
  getCandoJob: (...a) => getCandoJob(...a),
  stopCandoJob: async () => ({}),
  getDesign: (...a) => getDesign(...a),
  getCandoProgress: async () => ({ overall: 1 }),
  deleteCandoJob: async () => ({}),
  syncDesignResponse: () => {},
}))

function mountDom() {
  document.body.innerHTML = `
    <div id="cando-jobs-panel">
      <div id="cando-jobs-heading"></div>
      <div id="cando-jobs-body">
        <div id="cando-jobs-list"></div>
        <button id="cando-jobs-autorefine-btn">Autorefine</button>
        <button id="cando-jobs-autorefine-stop-btn"></button>
        <div id="cando-jobs-autorefine-status"></div>
        <div id="cando-jobs-autorefine-result"></div>
      </div>
    </div>`
}
async function flush() { await new Promise((r) => setTimeout(r, 0)) }

describe('CanDo autorefine JOB (auto-apply) flow', () => {
  let initCandoJobsPanel
  beforeEach(async () => {
    vi.clearAllMocks()
    mountDom()
    ;({ initCandoJobsPanel } = await import('./cando_jobs_panel.js'))
  })

  it('launches a kind=autorefine job, shows the applied result, and refreshes the design', async () => {
    initCandoJobsPanel({})
    document.getElementById('cando-jobs-autorefine-btn').click()
    await flush(); await flush(); await flush()   // create → poll(complete) → getDesign → fetchJobs

    // A kind=autorefine job was created (not the old separate-run start).
    expect(createCandoJob).toHaveBeenCalledWith(expect.objectContaining({ kind: 'autorefine' }))
    // The design was refreshed after the server-side auto-apply.
    expect(getDesign).toHaveBeenCalled()

    const result = document.getElementById('cando-jobs-autorefine-result')
    expect(result.textContent).not.toContain('No improving')
    expect(result.textContent).toContain('Applied 26 loop/skip marks')
    expect(result.textContent).toContain('period 36')
    expect(result.textContent).toContain('deviation 0.72 nm')
    // No manual "Apply to design" button — the job already applied.
    expect(result.querySelector('button')).toBeNull()

    const status = document.getElementById('cando-jobs-autorefine-status')
    expect(status.textContent).toContain('Applied 26 marks')
  })
})
