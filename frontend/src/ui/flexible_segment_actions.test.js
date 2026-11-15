import { afterEach, expect, it, vi } from 'vitest'
import { createFlexibleSegmentActions } from './flexible_segment_actions.js'

const run = [104, 105].map(bp_index => ({ strand_id: 'scaffold', domain_index: 0, bp_index, direction: 'REVERSE' }))
afterEach(() => document.body.replaceChildren())
function setup(batchFlexibleSegment) {
  const showToast = vi.fn()
  const mark = createFlexibleSegmentActions({ api: { batchFlexibleSegment }, showToast,
    beginOperationTiming: vi.fn(), markOperationTiming: vi.fn() })
  return { mark, showToast }
}
it('shows the requested rejection popup without claiming success', async () => {
  const message = 'flexible connections must be between two different cluster'
  const api = vi.fn(async (_body, { onError }) => {
    onError(422, { code: 'flexible_connection_requires_distinct_clusters', message })
    return null
  })
  const { mark, showToast } = setup(api)
  await mark(run)
  expect(api.mock.calls[0][0]).toEqual({ marks: run })
  expect(document.querySelector('.modal__body').textContent).toBe(message)
  expect(showToast).toHaveBeenCalledExactlyOnceWith('Marking 2-base flexible segment…')
  document.querySelector('.modal__actions button').click()
})
it('confirms a two-base tether only after persistence', async () => {
  let resolve
  const { mark, showToast } = setup(() => new Promise(r => { resolve = r }))
  const pending = mark(run)
  expect(showToast).toHaveBeenCalledExactlyOnceWith('Marking 2-base flexible segment…')
  resolve({ design: { flexible_connections: [{ id: 'tether', segment_bead_keys: run }] } })
  await pending
  expect(showToast.mock.lastCall[0]).toBe('Marked 2-base flexible segment')
})
it('does not claim success for a failed or retired request', async () => {
  const { mark, showToast } = setup(async () => null)
  await mark(run)
  expect(showToast).toHaveBeenCalledTimes(1)
  const failed = setup(async () => { throw new Error('Rejected') })
  await expect(failed.mark(run)).rejects.toThrow('Rejected')
  expect(failed.showToast).toHaveBeenCalledTimes(1)
})
