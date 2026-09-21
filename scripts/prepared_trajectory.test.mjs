import { test } from 'node:test'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import assert from 'node:assert/strict'
import { gzipSync } from 'node:zlib'
import { encodeContainer, decodeContainer } from '../frontend/src/viewer/package_container.js'
import { sceneChannels, encodeFrame } from '../frontend/src/viewer/trajectory_clip.js'
import { unpackTrajectory, updateTrajectory } from './prepared_trajectory.mjs'
import { createPreparedHost } from './prepared_view_host.mjs'
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const data = () => ({ root: { type: 'Scene', name: '', matrix: [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1], children: [] }, geometries: [], materials: [], images: [], textures: [] })
test('host separates validated compressed frames from the initial package', () => {
  const d = data(), base = sceneChannels(d); d.root.matrix[12] = 3
  const frame = new Uint8Array(gzipSync(Buffer.from(encodeFrame(base, sceneChannels(d)))))
  d.root.matrix[12] = 0
  d.trajectory = { version: 1, encoding: 'absolute-render-patch-gzip', fps: 8, sourceFrames: [0, 1], frames: [frame, frame] }
  const result = unpackTrajectory(Buffer.from(encodeContainer(d)))
  const scene = decodeContainer(result.scene.buffer.slice(result.scene.byteOffset, result.scene.byteOffset + result.scene.byteLength))
  assert.equal(result.trajectory.frames.length, 2)
  assert.equal(scene.trajectory.frames[0].bytes, frame.byteLength)
  assert.match(scene.trajectory.frames[0].sha256, /^[a-f0-9]{64}$/)
  assert.equal(scene.trajectory.frames[0] instanceof Uint8Array, false)
  let state
  const room = { trajectory: result.trajectory, presentation: { setTrajectory: v => { state = v; return v } } }
  updateTrajectory(room, { id: result.trajectory.id, frame: 1, fps: 15, playing: true }, () => 100)
  assert.equal(state.at, 100)
  assert.throws(() => updateTrajectory(room, { id: 'obsolete', frame: 1, fps: 8, playing: true }, () => 100))
  d.trajectory.frames = [new Uint8Array([1,2,3]), frame]
  assert.throws(() => unpackTrajectory(Buffer.from(encodeContainer(d))))
})

test('frame transfers require a room cookie and timeline writes require presenter authority', async t => {
  const root = await mkdtemp(join(tmpdir(), 'nadoc-clip-host-')); t.after(() => rm(root, { recursive: true, force: true }))
  await mkdir(join(root, 'assets')); await writeFile(join(root, 'viewer.html'), 'viewer')
  const host = await createPreparedHost({ dist: root }); t.after(host.stop)
  await new Promise(ok => host.server.listen(0, '127.0.0.1', ok))
  const url = `http://127.0.0.1:${host.server.address().port}`; host.setPublicBase(url)
  const d = data(), base = sceneChannels(d), frame = new Uint8Array(gzipSync(Buffer.from(encodeFrame(base, base))))
  d.trajectory = { version: 1, encoding: 'absolute-render-patch-gzip', fps: 8, sourceFrames: [0, 1], frames: [frame, frame] }
  const share = host.createShare(Buffer.from(encodeContainer(d))), endpoint = `${url}/meeting/${share.id}`
  const path = `${endpoint}/frame?clip=${share.trajectory.id}&index=1`
  assert.equal((await fetch(path)).status, 401)
  const joined = await fetch(endpoint + '/join', { method: 'POST', headers: { Origin: url }, body: JSON.stringify({ name: 'Guest', token: new URLSearchParams(new URL(share.url).hash.slice(1)).get('invite') }) })
  const cookie = joined.headers.get('set-cookie').split(';')[0], headers = { Cookie: cookie, Origin: url }
  const response = await fetch(path, { headers }); assert.equal(response.status, 200)
  assert.deepEqual(Buffer.from(await response.arrayBuffer()), Buffer.from(frame))
  const body = JSON.stringify({ id: share.trajectory.id, frame: 1, playing: true, fps: 8 })
  assert.equal((await fetch(endpoint + '/trajectory', { method: 'POST', headers, body })).status, 403)
  const control = `${url}/host/shares/${share.id}/trajectory`, auth = { Authorization: `Bearer ${host.controlToken}` }
  assert.equal((await fetch(control, { method: 'POST', headers, body })).status, 403)
  const published = await fetch(control, { method: 'POST', headers: auth, body }); assert.equal(published.status, 200)
  const controlFile = join(root, 'control.json')
  await writeFile(controlFile, JSON.stringify({ url, token: host.controlToken }))
  const viaHelper = await promisify(execFile)(process.execPath, ['scripts/prepared_share_request.mjs', controlFile, `/host/shares/${share.id}/trajectory`, 'GET'])
  assert.equal(JSON.parse(viaHelper.stdout).value.trajectory.frame, 1)
  const snapshot = await (await fetch(endpoint + '/status', { headers })).json()
  assert.equal(snapshot.presentation.trajectory.frame, 1)
  assert.equal(snapshot.presentation.trajectory.playing, true)
  await fetch(`${url}/host/shares/${share.id}`, { method: 'DELETE', headers: auth })
  assert.equal((await fetch(path, { headers })).status, 410)
})

test('one invitation switches static → trajectory → static without resetting guest authority', async t => {
  const root = await mkdtemp(join(tmpdir(), 'nadoc-unified-share-')); t.after(() => rm(root, { recursive: true, force: true }))
  await mkdir(join(root, 'assets')); await writeFile(join(root, 'viewer.html'), 'viewer')
  const host = await createPreparedHost({ dist: root }); t.after(host.stop)
  await new Promise(ok => host.server.listen(0, '127.0.0.1', ok))
  const url = `http://127.0.0.1:${host.server.address().port}`; host.setPublicBase(url)
  const original = Buffer.from(encodeContainer(data())), share = host.createShare(original, 'Original'), endpoint = `${url}/meeting/${share.id}`
  const joined = await fetch(endpoint + '/join', { method: 'POST', headers: { Origin: url }, body: JSON.stringify({ name: 'Guest', token: new URLSearchParams(new URL(share.url).hash.slice(1)).get('invite') }) })
  const cookie = joined.headers.get('set-cookie').split(';')[0], guest = { Cookie: cookie, Origin: url }, auth = { Authorization: `Bearer ${host.controlToken}` }
  const path = `${url}/host/shares/${share.id}/content`, d = data(), base = sceneChannels(d)
  const frame = new Uint8Array(gzipSync(Buffer.from(encodeFrame(base, base))))
  d.trajectory = { version: 1, encoding: 'absolute-render-patch-gzip', fps: 8, sourceFrames: [0, 1], frames: [frame, frame] }
  const body = Buffer.from(encodeContainer(d))
  assert.equal((await fetch(path, { method: 'POST', headers: guest, body })).status, 403)
  const response = await fetch(path, { method: 'POST', headers: { ...auth, 'X-NADOC-Title': 'With%20trajectory' }, body })
  assert.equal(response.status, 200)
  const clip = await response.json()
  for (const key of ['id', 'url', 'presenterUrl', 'expiresAt']) assert.equal(clip[key], share[key])
  assert.equal(clip.title, 'With trajectory'); assert.notEqual(clip.revision, share.revision)
  const status = () => fetch(endpoint + '/status', { headers: guest }).then(r => r.json())
  let state = await status(); assert.equal(state.name, 'Guest'); assert.equal(state.role, 'guest'); assert.equal(state.presentation.trajectory.id, clip.trajectory.id)
  const framePath = `${endpoint}/frame?clip=${clip.trajectory.id}&index=1`
  assert.equal((await fetch(framePath, { headers: guest })).status, 200)
  // A malformed replacement cannot destroy the existing scene/timeline.
  assert.equal((await fetch(path, { method: 'POST', headers: auth, body: 'invalid' })).status, 409)
  assert.equal((await status()).revision, clip.revision)
  assert.equal((await fetch(endpoint + '/trajectory', { method: 'POST', headers: guest, body: '{}' })).status, 403)
  const control = join(root, 'control.json'), file = join(root, 'view.nadocview')
  await writeFile(control, JSON.stringify({ url, token: host.controlToken })); await writeFile(file, original)
  const result = await promisify(execFile)(process.execPath, ['scripts/prepared_share_request.mjs', control, `/host/shares/${share.id}/content`, 'POST', file])
  assert.equal(JSON.parse(result.stdout).status, 200)
  state = await status(); assert.equal(state.name, 'Guest'); assert.equal(state.revision, share.revision); assert.equal(state.presentation.trajectory, null)
  assert.equal((await fetch(framePath, { headers: guest })).status, 404)
  assert.equal((await (await fetch(url + '/host/shares', { headers: auth })).json()).shares.length, 1)
})
