import { it, expect } from 'vitest'
import { hasCompleteSeekHistory } from './feature_seek_history.js'

it('does not acknowledge stripped or partially backfilled history', () => {
  const entry = { feature_type: 'snapshot', design_snapshot_gz_b64: 'pre', post_state_gz_b64: 'post' }
  expect(hasCompleteSeekHistory({ feature_log: [entry] })).toBe(true)
  expect(hasCompleteSeekHistory({ feature_log: [{ ...entry, post_state_gz_b64: '' }] })).toBe(false)
  expect(hasCompleteSeekHistory({ feature_log: [{ ...entry, children: [{ diff_added_b64: '1' }] }] })).toBe(false)
  expect(hasCompleteSeekHistory({ feature_log: [{ feature_type: 'snapshot', evicted: true }] })).toBe(true)
  expect(hasCompleteSeekHistory(null)).toBe(false)
})

import { createSeekHistoryAcknowledgement } from './feature_seek_history.js'
it('only acknowledges verified seek history, not a newer partial GET revision', () => {
  const history = createSeekHistoryAcknowledgement()
  const design = { id: 'd', feature_log: [{ id: 'f', feature_type: 'snapshot', design_snapshot_gz_b64: 'pre', post_state_gz_b64: 'post' }] }
  expect(history.knownRevision(design, 0)).toBeNull()
  history.acknowledge(design, 7, 0)
  // New design/metadata objects do not attest newer history: keep revision 7.
  expect(history.knownRevision({ ...design }, 0)).toBe(7)
  expect(history.knownRevision(design, 1)).toBeNull()
  design.feature_log[0].post_state_gz_b64 = 'edited in place'
  expect(history.knownRevision(design, 0)).toBeNull()
  history.reset()
  expect(history.knownRevision(design, 0)).toBeNull()
})
