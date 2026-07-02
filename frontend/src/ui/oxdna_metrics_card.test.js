/**
 * Factory-wiring test for the oxDNA "Graphs and Metrics" card.
 *
 * jsdom DOM (the card ids) + mocked api client + mocked popup/export modules.
 * Asserts the observable contract: Generate → poll → progress bar fills →
 * Display/Export enable → Display opens the popup; scope switch re-keys the cache.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

const start = vi.fn()
const poll = vi.fn()
vi.mock('../api/client.js', () => ({
  startOxdnaMetrics: (...a) => start(...a),
  getOxdnaMetricsRun: (...a) => poll(...a),
}))
const openPopup = vi.fn()
vi.mock('./metric_graph_popup.js', () => ({
  openMetricGraphPopup: (...a) => openPopup(...a),
  metricSpecs: () => ({ spatial: {}, temporal: {} }),
}))

import { initOxdnaMetricsCard } from './oxdna_metrics_card.js'

const IDS = {
  'oxdna-metrics-card': 'div',
  'oxdna-metrics-toggle': 'div',
  'oxdna-metrics-arrow': 'span',
  'oxdna-metrics-scope-latest': 'input',
  'oxdna-metrics-scope-chain': 'input',
}
for (const tok of ['twist', 'curve', 'bp']) {
  IDS[`oxdna-metrics-${tok}-gen`] = 'button'
  IDS[`oxdna-metrics-${tok}-display`] = 'button'
  IDS[`oxdna-metrics-${tok}-export`] = 'button'
  IDS[`oxdna-metrics-${tok}-bar`] = 'div'
  IDS[`oxdna-metrics-${tok}-fill`] = 'div'
  IDS[`oxdna-metrics-${tok}-status`] = 'div'
}

function makeResult() {
  return {
    ready: true, scope: 'latest', jobs: ['job123'],
    twist: { temporal: { per_frame: [1, 2, 3], boundaries: [] },
             spatial: [{ job_id: 'job123', points: [[0, 0], [5, 10]] }] },
    curvature: { temporal: { per_frame: [0.1, 0.2, 0.3], boundaries: [] },
                 spatial: [{ job_id: 'job123', points: [[0, 0], [5, 1]] }] },
    base_pairing: { temporal: { per_frame: [1, 0.99, 0.98], boundaries: [], n_designed: 100 },
                    spatial: [{ job_id: 'job123', points: [[0, 1], [5, 0.9]] }] },
  }
}

beforeEach(() => {
  clearDom(); mountIds(IDS)
  start.mockReset(); poll.mockReset(); openPopup.mockReset()
})

describe('initOxdnaMetricsCard', () => {
  it('Generate → done → progress full, Display/Export enabled, popup opens', async () => {
    start.mockResolvedValue({ metrics_id: 'r1', state: 'running' })
    poll.mockResolvedValue({ state: 'done', progress: 1, eta_s: 0, frames_done: 3,
                             frames_total: 3, result: makeResult() })
    const card = initOxdnaMetricsCard({ getSelectedJob: () => ({ job_id: 'job123' }), getJobs: () => [] })

    const gen = document.getElementById('oxdna-metrics-twist-gen')
    const disp = document.getElementById('oxdna-metrics-twist-display')
    expect(disp.disabled).toBe(true)                        // nothing computed yet
    gen.click()

    await vi.waitFor(() => expect(disp.disabled).toBe(false))
    expect(start).toHaveBeenCalledWith('job123', { scope: 'latest' })
    expect(document.getElementById('oxdna-metrics-twist-fill').style.width).toBe('100%')
    // one pass computed every metric → curvature display also enabled
    expect(document.getElementById('oxdna-metrics-curve-display').disabled).toBe(false)

    disp.click()
    expect(openPopup).toHaveBeenCalledTimes(1)
    expect(openPopup.mock.calls[0][0].metric).toBe('twist')
  })

  it('needs a job — no job → status warns, no request', async () => {
    const card = initOxdnaMetricsCard({ getSelectedJob: () => null, getJobs: () => [] })
    document.getElementById('oxdna-metrics-twist-gen').click()
    await Promise.resolve()
    expect(start).not.toHaveBeenCalled()
    expect(document.getElementById('oxdna-metrics-twist-status').textContent).toMatch(/job/i)
  })

  it('header toggles the card body (starts collapsed)', () => {
    initOxdnaMetricsCard({ getSelectedJob: () => null, getJobs: () => [] })
    const body = document.getElementById('oxdna-metrics-card')
    const toggle = document.getElementById('oxdna-metrics-toggle')
    body.style.display = 'none'                              // HTML default (collapsed)
    toggle.click(); expect(body.style.display).toBe('')      // expands
    toggle.click(); expect(body.style.display).toBe('none')  // collapses
  })

  it('scope switch re-keys the cache — chain has no cached result yet', async () => {
    start.mockResolvedValue({ metrics_id: 'r1', state: 'running' })
    poll.mockResolvedValue({ state: 'done', progress: 1, result: makeResult() })
    initOxdnaMetricsCard({ getSelectedJob: () => ({ job_id: 'job123' }), getJobs: () => [] })
    const disp = document.getElementById('oxdna-metrics-twist-display')
    document.getElementById('oxdna-metrics-twist-gen').click()
    await vi.waitFor(() => expect(disp.disabled).toBe(false))   // latest cached
    // switch to chain scope → nothing cached there → display disabled
    const chain = document.getElementById('oxdna-metrics-scope-chain')
    chain.checked = true; chain.dispatchEvent(new Event('change'))
    expect(disp.disabled).toBe(true)
  })
})
