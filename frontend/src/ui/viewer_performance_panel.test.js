import { afterEach, expect, it, vi } from 'vitest'
import { mountViewerPerformancePanel } from './viewer_performance_panel.js'
import { getViewerPerformance } from '../perf/viewer_performance.js'
vi.mock('../perf/viewer_performance.js', () => ({ getViewerPerformance: vi.fn() }))
afterEach(() => { document.body.replaceChildren(); vi.clearAllMocks() })

it('starts an explicitly labeled capture, closes the panel for measurement, and unsubscribes', async () => {
  const unsubscribe = vi.fn()
  const api = { start: vi.fn().mockResolvedValue(), subscribe: vi.fn(() => unsubscribe), busy: false, latest: null, defaultVariant: 'B' }
  getViewerPerformance.mockReturnValue(api)
  const started = vi.fn()
  const dispose = mountViewerPerformancePanel(document.body, started)
  expect(document.querySelector('[data-perf-variant]').value).toBe('B')
  document.querySelector('[data-perf-start]').click()
  await vi.waitFor(() => expect(started).toHaveBeenCalledOnce())
  expect(api.start).toHaveBeenCalledWith({ variant: 'B', scenario: 'orbit', durationMs: 20000 })
  dispose()
  expect(unsubscribe).toHaveBeenCalledOnce()
  expect(document.body.children).toHaveLength(0)
})

it('keeps an error visible and provides a selectable clipboard fallback', async () => {
  const api = { start: vi.fn().mockRejectedValue(new Error('Load a part first')), subscribe: () => () => {}, busy: false,
    latest: { valid: false, invalid_reason: 'Stopped', frame_intervals: { samples: 0 } } }
  getViewerPerformance.mockReturnValue(api)
  mountViewerPerformancePanel(document.body)
  document.querySelector('[data-perf-start]').click()
  await vi.waitFor(() => expect(document.body.textContent).toContain('Load a part first'))
  document.querySelector('[data-perf-copy]').click()
  await vi.waitFor(() => expect(document.body.textContent).toContain('normal Copy command'))
  expect(document.querySelector('textarea').value).toContain('[NADOC_VIEWER_PERF v1]')
})
