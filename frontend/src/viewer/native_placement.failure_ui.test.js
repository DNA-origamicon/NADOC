import { afterEach, expect, it, vi } from 'vitest'
import { lastPlacementFailure, placementIntegrityFailure, PLACEMENT_FAILURE_EVENT, initNativePlacementIntegrityMonitor } from './native_placement.js'

afterEach(() => {
  document.getElementById('native-placement-integrity-block')?.remove()
  vi.unstubAllGlobals()
})

it('[native-placement] blocks the view, shows the exact failed site, and saves a review report', async () => {
  const fetch = vi.fn(async () => ({ ok: true, json: async () => ({ incident_id: 'test-incident', report_path: '/test/report.json', review_required: true }) }))
  vi.stubGlobal('fetch', fetch)
  const event = vi.fn()
  window.addEventListener(PLACEMENT_FAILURE_EVENT, event, { once: true })
  expect(() => placementIntegrityFailure({ helix_id: 'H12', bp_index: 17, direction: 'REVERSE' },
    'slab_position', [null, 2, 3], 'Nonfinite canonical coordinate')).toThrow(/full placement review/)
  const panel = document.getElementById('native-placement-integrity-block')
  expect(panel.getAttribute('role')).toBe('alertdialog')
  expect(panel.style.background).toBe('rgb(20, 23, 29)')
  expect(panel.textContent).toContain('H12:17:REVERSE')
  expect(panel.textContent).toContain('slab_position')
  expect(panel.textContent).toContain('Nonfinite canonical coordinate')
  expect(panel.querySelector('button').textContent).toContain('Download')
  expect(event).toHaveBeenCalledOnce()
  await vi.waitFor(() => expect(fetch).toHaveBeenCalledOnce())
  expect(fetch.mock.calls[0][0]).toBe('/api/design/placement-integrity-report')
  const sent = JSON.parse(fetch.mock.calls[0][1].body)
  expect(sent).toMatchObject({ code: 'NATIVE_PLACEMENT_INTEGRITY', identity: 'H12:17:REVERSE', field: 'slab_position' })
  await vi.waitFor(() => expect(lastPlacementFailure().incident_id).toBe('test-incident'))
  expect(panel.textContent).toContain('test-incident')
})

it('[native-placement] keeps a downloadable report visible when server delivery fails', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('test network unavailable') }))
  expect(() => placementIntegrityFailure(null, 'placement_source', 'legacy')).toThrow()
  await vi.waitFor(() => expect(lastPlacementFailure().report_delivery_error).toContain('test network unavailable'))
  const panel = document.getElementById('native-placement-integrity-block')
  expect(panel.textContent).toContain('server did not save this report')
  expect(panel.querySelector('button')).not.toBeNull()
})

it('[native-placement] blocks on an unreadable review journal even when the status response is HTTP503', async () => {
  const fetch = vi.fn(async () => ({ ok: false, status: 503, json: async () => ({
    review_required: true, incidents: [], message: 'The placement review journal could not be read.',
    report_delivery_error: 'invalid JSON in pending-review.json',
  }) }))
  vi.stubGlobal('fetch', fetch)
  const stop = initNativePlacementIntegrityMonitor()
  try {
    await vi.waitFor(() => expect(document.getElementById('native-placement-integrity-block')).not.toBeNull())
    const panel = document.getElementById('native-placement-integrity-block')
    expect(panel.textContent).toContain('journal could not be read')
    expect(panel.textContent).toContain('invalid JSON in pending-review.json')
    expect(fetch.mock.calls.every(([url]) => url === '/api/design/placement-integrity-status')).toBe(true)
  } finally { stop() }
})
