import { expect, it } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { createFeatureHistoryFeedback, historyFailureStatus } from './feature_history_feedback.js'

function fixture() {
  const source = { id: 'part', feature_log: [{ id: 'base' },
    { id: 'routing', feature_type: 'routing-cluster', children: [{ id: 'nick' }, { id: 'later-nick' }] },
    { id: 'tail' }] }
  const store = createMockStore({ currentDesign: source })
  const events = new EventTarget(), feedback = createFeatureHistoryFeedback(store, events)
  const error = Object.assign(new Error('A target is missing'), { detail: { feature_id: 'nick' } })
  return { source, store, events, feedback, error }
}
it('marks the first refusal and unregenerated suffix without changing the design', () => {
  const f = fixture(), saved = JSON.stringify(f.source)
  f.feedback.update(f.error)
  const failure = f.store.getState().featureHistoryFailure
  expect(historyFailureStatus(failure, f.source, f.source.feature_log[0])).toBeNull()
  expect(historyFailureStatus(failure, f.source, f.source.feature_log[1]).state).toBe('error')
  expect(historyFailureStatus(failure, f.source, { id: 'later-nick' }).state).toBe('blocked')
  expect(historyFailureStatus(failure, f.source, { id: 'tail' }).reason).toContain('saved part is unchanged')
  expect(JSON.stringify(f.source)).toBe(saved)
  f.feedback.dispose()
})
it.each(['clear', 'retry', 'replacement', 'reset', 'dispose'])('clears feedback on %s', action => {
  const f = fixture(); f.feedback.update(f.error)
  if (action === 'replacement') f.store.setState({ currentDesign: { ...f.source } })
  else if (action === 'reset') f.events.dispatchEvent(new Event('nadoc:document-reset'))
  else if (action === 'retry') f.feedback.update(null)
  else f.feedback[action]()
  expect(f.store.getState().featureHistoryFailure).toBeNull()
  f.feedback.dispose()
})
it('ignores stale sources and failures without a history feature identity', () => {
  const f = fixture()
  f.feedback.update(f.error, { ...f.source })
  expect(f.store.getState().featureHistoryFailure).toBeUndefined()
  f.feedback.update(new Error('Network unavailable'))
  expect(f.store.getState().featureHistoryFailure).toBeUndefined()
  f.feedback.dispose()
})
it('does not clear another editor owner and does not publish repeated errors', () => {
  const f = fixture(), second = createFeatureHistoryFeedback(f.store, f.events)
  f.feedback.update(f.error)
  const first = f.store.getState().featureHistoryFailure
  f.feedback.update(f.error)
  expect(f.store.getState().featureHistoryFailure).toBe(first)
  second.update(f.error); f.feedback.dispose()
  expect(f.store.getState().featureHistoryFailure).not.toBeNull()
  second.dispose()
})
