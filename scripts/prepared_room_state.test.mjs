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

test('selection pings preserve scene and perspective and are cleared on replacement', () => {
  const revision = 'a'.repeat(64), room = createPresentationState({ id: 'room', revision })
  room.publish({ revision, camera: pose })
  const value = { revision, target: 'cloud', selectionRevision: 2, ping: { id: 'ping-1', createdAt: Date.now() } }
  room.publishSelectionPing(value)
  assert.equal(room.snapshot().revision, revision)
  assert.equal(room.snapshot().presenting, true)
  assert.deepEqual(room.snapshot().camera, pose)
  assert.deepEqual(room.snapshot().selectionPing, value)
  const sequence = room.snapshot().sequence
  room.publishSelectionPing(value); assert.equal(room.snapshot().sequence, sequence)
  assert.throws(() => room.publishSelectionPing({ ...value, revision: 'b'.repeat(64) }), /snapshot/)
  assert.throws(() => room.publishSelectionPing({ ...value, ping: { id: 'x', createdAt: -1 } }), /Invalid/)
  room.replaceRevision('b'.repeat(64)); assert.equal(room.snapshot().selectionPing, null)
  room.close()
})

test('selection state reaches late guests once, without repeating geometry in camera events', () => {
  const revision = 'a'.repeat(64), room = createPresentationState({ id: 'room', revision })
  const selection = { revision, id: 'update-one', selection: { target: 'cloud', revision: 1, label: 'Base', ping: null }, points: [1,2,3], corners: [], tints: [] }
  room.publishSelectionUpdate(selection)
  const response = new EventEmitter(); response.write = value => { response.last = value; return true }; response.end = () => response.emit('close')
  room.subscribe(response)
  assert.match(response.last, /"selectionUpdate":/)
  room.publish({ revision, camera: pose })
  assert.doesNotMatch(response.last, /"selectionUpdate":/)
  assert.equal(room.snapshot().revision, revision)
  assert.deepEqual(room.snapshot().selectionUpdate, selection)
  const late = new EventEmitter(); late.write = value => { late.last = value; return true }; late.end = () => late.emit('close')
  room.subscribe(late); assert.match(late.last, /"selectionUpdate":/)
  assert.throws(() => room.publishSelectionUpdate({ ...selection, revision: 'b'.repeat(64) }), /snapshot/)
  room.replaceRevision('b'.repeat(64)); assert.equal(room.snapshot().selectionUpdate, null)
  assert.match(late.last, /"selectionUpdate":null/)
  room.close()
})
