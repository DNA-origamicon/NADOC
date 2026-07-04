/**
 * Factory-wiring test for the MD "Graphs and Metrics" card.
 *
 * The MD twin of oxdna_metrics_card.test.js: same shared factory (metrics_card.js),
 * bound to the `md-metrics-*` ids and the MD REST surface. Asserts the observable
 * contract: Generate → poll → progress bar fills → Display/Export enable → Display
 * opens the popup; scope switch re-keys the cache.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

const start = vi.fn()
const poll = vi.fn()
vi.mock('../api/client.js', () => ({
  startMdMetrics: (...a) => start(...a),
  getMdMetricsRun: (...a) => poll(...a),
}))
const openPopup = vi.fn()
vi.mock('./metric_graph_popup.js', () => ({
  openMetricGraphPopup: (...a) => openPopup(...a),
  metricSpecs: () => ({ spatial: {}, temporal: {} }),
}))

import { initMdMetricsCard } from './md_metrics_card.js'

const IDS = {
  'md-metrics-card': 'div',
  'md-metrics-toggle': 'div',
  'md-metrics-arrow': 'span',
  'md-metrics-scope-latest': 'input',
  'md-metrics-scope-chain': 'input',
}
for (const tok of ['twist', 'curve', 'bp']) {
  IDS[`md-metrics-${tok}-gen`] = 'button'
  IDS[`md-metrics-${tok}-display`] = 'button'
  IDS[`md-metrics-${tok}-export`] = 'button'
  IDS[`md-metrics-${tok}-bar`] = 'div'
  IDS[`md-metrics-${tok}-fill`] = 'div'
  IDS[`md-metrics-${tok}-status`] = 'div'
}

function makeResult() {
  return {
    ready: true, scope: 'latest', jobs: ['md123'],
    twist: { temporal: { per_frame: [1, 2, 3], boundaries: [] },
             spatial: [{ job_id: 'md123', points: [[0, 0], [5, 10]] }] },
    curvature: { temporal: { per_frame: [0.1, 0.2, 0.3], boundaries: [] },
                 spatial: [{ job_id: 'md123', points: [[0, 0], [5, 1]] }] },
    base_pairing: { temporal: { per_frame: [1, 0.99, 0.98], boundaries: [], n_designed: 100 },
                    spatial: [{ job_id: 'md123', points: [[0, 1], [5, 0.9]] }] },
  }
}

beforeEach(() => {
  clearDom(); mountIds(IDS)
  start.mockReset(); poll.mockReset(); openPopup.mockReset()
})

describe('initMdMetricsCard', () => {
  it('Generate → done → progress full, Display/Export enabled, popup opens', async () => {
    start.mockResolvedValue({ metrics_id: 'r1', state: 'running' })
    poll.mockResolvedValue({ state: 'done', progress: 1, eta_s: 0, frames_done: 3,
                             frames_total: 3, result: makeResult() })
    initMdMetricsCard({ getSelectedJob: () => ({ job_id: 'md123' }), getJobs: () => [] })

    const gen = document.getElementById('md-metrics-twist-gen')
    const disp = document.getElementById('md-metrics-twist-display')
    expect(disp.disabled).toBe(true)                        // nothing computed yet
    gen.click()

    await vi.waitFor(() => expect(disp.disabled).toBe(false))
    expect(start).toHaveBeenCalledWith('md123', { scope: 'latest' })
    expect(document.getElementById('md-metrics-twist-fill').style.width).toBe('100%')
    // one pass computed every metric → base-pairing display also enabled
    expect(document.getElementById('md-metrics-bp-display').disabled).toBe(false)

    disp.click()
    expect(openPopup).toHaveBeenCalledTimes(1)
    expect(openPopup.mock.calls[0][0].metric).toBe('twist')
  })

  it('needs a job — no job → status warns, no request', async () => {
    initMdMetricsCard({ getSelectedJob: () => null, getJobs: () => [] })
    document.getElementById('md-metrics-twist-gen').click()
    await Promise.resolve()
    expect(start).not.toHaveBeenCalled()
    expect(document.getElementById('md-metrics-twist-status').textContent).toMatch(/job/i)
  })

  it('scope switch re-keys the cache — chain has no cached result yet', async () => {
    start.mockResolvedValue({ metrics_id: 'r1', state: 'running' })
    poll.mockResolvedValue({ state: 'done', progress: 1, result: makeResult() })
    initMdMetricsCard({ getSelectedJob: () => ({ job_id: 'md123' }), getJobs: () => [] })
    const disp = document.getElementById('md-metrics-twist-display')
    document.getElementById('md-metrics-twist-gen').click()
    await vi.waitFor(() => expect(disp.disabled).toBe(false))   // latest cached
    const chain = document.getElementById('md-metrics-scope-chain')
    chain.checked = true; chain.dispatchEvent(new Event('change'))
    expect(disp.disabled).toBe(true)
  })
})
