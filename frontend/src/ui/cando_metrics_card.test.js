/**
 * Factory-wiring test for the CanDo "Graphs and Metrics" card.
 *
 * jsdom DOM (the card ids) + mocked api client + mocked export modal.  Asserts the
 * observable contract: buttons gate on a completed job (+ RMSF availability),
 * Display fetches + opens the popup, and refresh clears the cache.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

const getRmsf = vi.fn()
const getDeviation = vi.fn()
vi.mock('../api/client.js', () => ({
  getCandoRmsf: (...a) => getRmsf(...a),
  getCandoDeviation: (...a) => getDeviation(...a),
}))
const openExport = vi.fn()
vi.mock('./metric_export_modal.js', () => ({
  openMetricExportModal: (...a) => openExport(...a),
  exportChoiceFiles: (c) => [c?.png && 'png', c?.data && 'data'].filter(Boolean),
  downloadText: vi.fn(),
  downloadHref: vi.fn(),
}))

import { initCandoMetricsCard } from './cando_metrics_card.js'

const IDS = {
  'cando-metrics-card': 'div',
  'cando-metrics-toggle': 'div',
  'cando-metrics-arrow': 'span',
}
for (const tok of ['rmsf', 'dev']) {
  IDS[`cando-metrics-${tok}-display`] = 'button'
  IDS[`cando-metrics-${tok}-export`] = 'button'
  IDS[`cando-metrics-${tok}-status`] = 'div'
}

const completedJob = { job_id: 'candojob1', status: 'completed', rmsf_max_nm: 1.3 }

beforeEach(() => {
  clearDom(); mountIds(IDS)
  getRmsf.mockReset(); getDeviation.mockReset(); openExport.mockReset()
})

describe('initCandoMetricsCard', () => {
  it('disables all buttons when no completed job is selected', () => {
    initCandoMetricsCard({ getSelectedJob: () => null })
    expect(document.getElementById('cando-metrics-rmsf-display').disabled).toBe(true)
    expect(document.getElementById('cando-metrics-dev-display').disabled).toBe(true)
    expect(document.getElementById('cando-metrics-rmsf-status').textContent).toMatch(/completed/i)
  })

  it('enables both metrics for a completed RMSF job; deviation stays on without RMSF', () => {
    const card = initCandoMetricsCard({ getSelectedJob: () => completedJob })
    card.sync()
    expect(document.getElementById('cando-metrics-rmsf-display').disabled).toBe(false)
    expect(document.getElementById('cando-metrics-dev-display').disabled).toBe(false)

    // A job without RMSF: flex disabled, deviation still enabled.
    const noRmsf = { job_id: 'j2', status: 'completed' }
    const card2 = initCandoMetricsCard({ getSelectedJob: () => noRmsf })
    card2.sync()
    expect(document.getElementById('cando-metrics-rmsf-display').disabled).toBe(true)
    expect(document.getElementById('cando-metrics-dev-display').disabled).toBe(false)
  })

  it('Display fetches rmsf and opens the popup with a canvas', async () => {
    getRmsf.mockResolvedValue({ rmsf: [
      { helix_id: 0, bp_index: 0, rmsf_nm: 0.5 },
      { helix_id: 0, bp_index: 1, rmsf_nm: 0.9 },
    ] })
    const card = initCandoMetricsCard({ getSelectedJob: () => completedJob })
    card.sync()
    document.getElementById('cando-metrics-rmsf-display').click()
    await vi.waitFor(() =>
      expect(document.getElementById('cando-metrics-rmsf-status').textContent).toMatch(/2 base pairs/))
    expect(getRmsf).toHaveBeenCalledWith('candojob1')
    expect(document.getElementById('cando-metric-popup-canvas')).toBeTruthy()
    expect(document.querySelector('#cando-metric-popup-title').textContent).toMatch(/RMSF/)
  })

  it('Export fetches deviation, opens the modal, and emits files on confirm', async () => {
    getDeviation.mockResolvedValue({ positions: [
      { helix_id: 0, bp_index: 0, deviation: 2.0 },
      { helix_id: 0, bp_index: 1, deviation: 3.0 },
    ] })
    openExport.mockResolvedValue({ png: true, data: true })
    const mod = await import('./metric_export_modal.js')
    const card = initCandoMetricsCard({ getSelectedJob: () => completedJob })
    card.sync()
    document.getElementById('cando-metrics-dev-export').click()
    await vi.waitFor(() => expect(mod.downloadText).toHaveBeenCalled())
    expect(getDeviation).toHaveBeenCalledWith('candojob1')
    expect(mod.downloadHref).toHaveBeenCalled()   // PNG
    expect(mod.downloadText.mock.calls[0][0]).toMatch(/cando_deviation_.*\.csv/)
  })

  it('caches a metric fetch (second Display does not refetch) and refresh clears it', async () => {
    getRmsf.mockResolvedValue({ rmsf: [{ helix_id: 0, bp_index: 0, rmsf_nm: 0.5 }] })
    const card = initCandoMetricsCard({ getSelectedJob: () => completedJob })
    card.sync()
    document.getElementById('cando-metrics-rmsf-display').click()
    await vi.waitFor(() => expect(getRmsf).toHaveBeenCalledTimes(1))
    document.getElementById('cando-metrics-rmsf-display').click()
    await vi.waitFor(() =>
      expect(document.getElementById('cando-metrics-rmsf-status').textContent).toMatch(/base pairs/))
    expect(getRmsf).toHaveBeenCalledTimes(1)       // served from cache
    card.refresh()
    document.getElementById('cando-metrics-rmsf-display').click()
    await vi.waitFor(() => expect(getRmsf).toHaveBeenCalledTimes(2))   // cache cleared → refetch
  })

  it('header toggles the card body (starts collapsed)', () => {
    initCandoMetricsCard({ getSelectedJob: () => null })
    const body = document.getElementById('cando-metrics-card')
    const toggle = document.getElementById('cando-metrics-toggle')
    body.style.display = 'none'
    toggle.click(); expect(body.style.display).toBe('')
    toggle.click(); expect(body.style.display).toBe('none')
  })
})
