import { test } from 'node:test'
import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { createRoomPresence } from './prepared_presence.mjs'

test('presence counts connections, preserves random display identity, and never exposes session secrets', () => {
  let roster
  const presence = createRoomPresence({ presentation: { setParticipants: value => { roster = value } } })
  const alice = { name: 'Alice', role: 'guest', secret: 'private' }, bob = { name: 'Bob', role: 'guest' }
  const id = presence.identify(alice), a = new EventEmitter(), duplicate = new EventEmitter(), b = new EventEmitter()
  presence.connect(alice, a); presence.connect(alice, duplicate); presence.connect(bob, b)
  assert.equal(roster.length, 3); assert.notEqual(alice.color, bob.color)
  assert.deepEqual(Object.keys(roster[0]).sort(), ['color', 'id', 'name', 'online'])
  a.emit('close'); assert.equal(roster.length, 3)
  duplicate.emit('close'); assert.equal(roster.length, 2)
  const color = alice.color
  presence.connect(alice, new EventEmitter()); assert.equal(presence.identify(alice), id); assert.equal(alice.color, color)
  b.emit('close'); assert.equal(roster.length, 2)
})

test('one-shot cameras are validated, revision-bound at publication, replaceable, and retained after leaving', () => {
  let time = 10000, roster
  const presence = createRoomPresence({ now: () => time, presentation: { snapshot: () => ({ revision: 'a' }), setParticipants: value => { roster = value } } })
  const session = { name: 'Ada', role: 'guest' }, stream = new EventEmitter()
  presence.connect(session, stream)
  const camera = { position: [0, 0, 20], target: [0, 0, 0], up: [0, 1, 0], fov: 55, near: .1, far: 2000, orbitMode: 'orbit' }
  assert.throws(() => presence.share(session, { revision: 'b', camera }), /latest visualization/)
  assert.throws(() => presence.share(session, { revision: 'a', camera: { ...camera, position: [NaN, 0, 0] } }), /Invalid/)
  presence.share(session, { revision: 'a', camera }); const first = roster[0].sharedView
  assert.throws(() => presence.share(session, { revision: 'a', camera }), /wait a moment/)
  time += 16000; presence.share(session, { revision: 'a', camera: { ...camera, position: [10, 0, 20] } })
  assert.ok(roster[0].sharedView.serial > first.serial); assert.equal(roster[0].sharedView.sharedAt, time)
  stream.emit('close'); assert.equal(roster[0].online, false); assert.deepEqual(roster[0].sharedView.camera.position, [10, 0, 20])
})

test('publishes only guest health flags, includes presenter, rejects metadata and expires stale reports', () => {
  let time = 10000, roster
  const presence = createRoomPresence({ now: () => time, presentation: { setParticipants: value => { roster = value } } })
  const session = { name: 'Ada', role: 'guest' }; presence.connect(session, new EventEmitter())
  assert.equal(roster.at(-1).role, 'presenter')
  assert.throws(() => presence.health(session, { networkSlow: true, renderSlow: false, gpu: 'device' }), /Only connection/)
  presence.health(session, { networkSlow: true, renderSlow: false })
  assert.deepEqual(roster[0].health, { networkSlow: true, renderSlow: false })
  assert.throws(() => presence.health(session, { networkSlow: false, renderSlow: false }), /frequent/)
  time += 30001; presence.expireHealth(); assert.equal(roster[0].health, undefined)
  assert.throws(() => presence.health({ role: 'guest' }, { networkSlow: true, renderSlow: true }), /Join/)
})
