import { test } from 'node:test'
import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { createPresentationState } from './prepared_room_state.mjs'
const pose = { position: [0, 0, 30], target: [0, 0, 0], up: [0, 1, 0], fov: 55, near: .1, far: 2000, orbitMode: 'orbit' }
test('camera state is bounded, snapshot-bound, ordered and sent to late joiners', () => {
  let now = 1000
  const room = createPresentationState({ id: 'room', revision: 'revision', now: () => now })
  assert.throws(() => room.publish({ revision: 'other', camera: pose }), /snapshot/)
  assert.throws(() => room.publish({ revision: 'revision', camera: { ...pose, position: [Infinity, 0, 1] } }), /camera/)
  assert.throws(() => room.publish({ revision: 'revision', camera: { ...pose, up: [0, 0, 0] } }), /camera/)
  assert.throws(() => room.publish({ revision: 'revision', camera: { ...pose, far: .01 } }), /camera/)
  room.publish({ revision: 'revision', camera: pose })
  const response = new EventEmitter(); response.write = value => { response.last = value; return true }; response.end = () => response.emit('close')
  room.subscribe(response)
  assert.match(response.last, /"sequence":1/); assert.match(response.last, /"presenting":true/)
  for (let i = 0; i < 19; i++) room.publish({ revision: 'revision', camera: pose })
  assert.throws(() => room.publish({ revision: 'revision', camera: pose }), /Too many/)
  now += 1000; room.publish({ revision: 'revision', camera: pose })
  assert.equal(room.snapshot().sequence, 21)
  room.pause(); assert.equal(room.snapshot().presenting, false)
  assert.deepEqual(room.snapshot().camera, pose)
  room.close()
})
test('stalled event consumers time out without buffering camera history', t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const room = createPresentationState({ id: 'r', revision: 'v' }), response = new EventEmitter()
  let destroyed = false
  response.write = () => false; response.destroy = () => { destroyed = true; response.emit('close') }
  room.subscribe(response); assert.equal(destroyed, false)
  t.mock.timers.tick(5000); assert.equal(destroyed, true); room.close()
})
test('animation lock is independent of the manual lock and survives scene replacements', () => {
  const room = createPresentationState({ id: 'room', revision: 'first' })
  room.setViewLock(true); room.setViewLock(true, true)
  room.replaceContent('next', null)
  assert.equal(room.snapshot().viewLocked, true)
  assert.equal(room.snapshot().animationActive, true)
  room.setViewLock(false, true)
  assert.equal(room.snapshot().viewLocked, true)
  room.setViewLock(false)
  assert.equal(room.snapshot().viewLocked, false)
  assert.throws(() => room.setViewLock('true'), /Invalid/)
  room.close()
})
