import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createRoomDrawings } from './prepared_drawings.mjs'
import { createPresentationState } from './prepared_room_state.mjs'
test('drawings expire, clear per author, and cannot cross scene revisions or authentication', () => {
  let now = 100
  const presentation = createPresentationState({ id: 'room', revision: 'r', now: () => now })
  const api = createRoomDrawings({ presentation, now: () => now })
  const session = { role: 'guest', streams: new Set([1]), participantId: 'one', color: '#a8d8ff' }
  const value = { revision: 'r', id: 'mark', points: [[0, 0], [.1, .1]], camera: { position: [0, 0, 20], target: [0, 0, 0], up: [0, 1, 0], fov: 55, near: .1, far: 100, orbitMode: 'orbit' } }
  assert.throws(() => api.publish({ ...session, streams: new Set() }, value), /Join/)
  assert.throws(() => api.publish(session, { ...value, revision: 'old' }), /current/)
  api.publish(session, value); api.publish({ ...session, participantId: 'two' }, value)
  assert.equal(api.snapshot().drawings.length, 2)
  api.publish(session, { revision: 'r', clear: true })
  assert.equal(api.snapshot().drawings[0].author, 'two')
  now += 2500; api.expire(); assert.deepEqual(presentation.snapshot().drawings, [])
  api.publish(session, value); presentation.replaceRevision('next')
  assert.deepEqual(api.snapshot().drawings, [])
  presentation.close()
})
