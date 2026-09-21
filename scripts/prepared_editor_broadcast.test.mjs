import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createEditorBroadcast } from './prepared_editor_broadcast.mjs'
import { createPresentationState } from './prepared_room_state.mjs'
const camera = { position: [0, 0, 10], target: [0, 0, 0], up: [0, 1, 0], fov: 55, near: .1, far: 1000, orbitMode: 'orbit' }
test('editor lease replaces revisions without touching invitations or guests and rejects late writes after stop/expiry', () => {
  let time = 0
  const room = { id: 'room', revision: 'old', scene: Buffer.from('NADOCVW1old'), sessions: new Map([['cookie', { role: 'guest' }]]) }
  room.presentation = createPresentationState({ id: room.id, revision: room.revision, now: () => time })
  room.editorBroadcast = createEditorBroadcast({ room, rooms: new Map([['room', room]]), maxGuests: 4, now: () => time })
  const api = room.editorBroadcast
  assert.throws(() => api.start({ cameraOnly: true, sourceHash: 'a'.repeat(64) }), /differs/)
  const { lease } = api.start(); assert.throws(() => api.start(), /Another editor/)
  api.apply('camera', lease, JSON.stringify({ revision: 'old', camera }))
  const next = Buffer.from('NADOCVW1new'), updated = api.apply('scene', lease, next)
  assert.notEqual(updated.revision, 'old'); assert.equal(room.presentation.snapshot().revision, updated.revision)
  assert.equal(room.presentation.snapshot().presenting, true); assert.equal(room.scene, next); assert.equal(room.sessions.has('cookie'), true)
  api.apply('pause', lease)
  assert.throws(() => api.apply('scene', lease, next), /stopped/)
  const newer = api.start(); assert.notEqual(newer.lease, lease)
  assert.throws(() => api.apply('camera', lease, JSON.stringify({ revision: updated.revision, camera })), /stopped/)
  time += 15001; api.expire(); assert.equal(api.active, false); assert.equal(room.presentation.snapshot().presenting, false)
})
test('editor presenter counts toward the four participant limit', () => {
  const room = { sessions: new Map(Array.from({ length: 4 }, (_, i) => [i, { role: 'guest' }])), presentation: createPresentationState({}) }
  const api = createEditorBroadcast({ room, rooms: new Map([['room', room]]), maxGuests: 4, now: Date.now })
  assert.throws(() => api.start(), /full/)
})
