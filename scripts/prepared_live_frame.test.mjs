import { test } from 'node:test'
import assert from 'node:assert/strict'
import { gzipSync } from 'node:zlib'
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { encodeContainer } from '../frontend/src/viewer/package_container.js'
import { sceneChannels, encodeFrame } from '../frontend/src/viewer/trajectory_clip.js'
import { createPreparedHost } from './prepared_view_host.mjs'
import { createShareBridge } from '../frontend/prepared_share_bridge.js'

test('stream packets use the same guest session, reject obsolete frames, survive private inspection, and reset to native', async t => {
  const root = await mkdtemp(join(tmpdir(), 'nadoc-live-test-')); t.after(() => rm(root, { recursive: true, force: true }))
  await mkdir(join(root, 'assets')); await writeFile(join(root, 'viewer.html'), 'viewer')
  const app = await createPreparedHost({ dist: root }); t.after(() => app.stop())
  await new Promise(ok => app.server.listen(0, '127.0.0.1', ok))
  const url = `http://127.0.0.1:${app.server.address().port}`; app.setPublicBase(url)
  const data = { root: { type: 'Scene', name: '', matrix: [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1], children: [] }, geometries: [], materials: [], images: [], textures: [] }
  const base = sceneChannels(data), scene = Buffer.from(encodeContainer(data)), share = app.createShare(scene)
  const host = async (action, body, lease = '') => fetch(`${url}/host/shares/${share.id}/broadcast/${action}`, { method: 'POST', headers: { Authorization: `Bearer ${app.controlToken}`, 'X-NADOC-Broadcast': lease }, body })
  const joinResponse = await fetch(`${url}/meeting/${share.id}/join`, { method: 'POST', headers: { Origin: url }, body: JSON.stringify({ token: new URLSearchParams(new URL(share.url).hash.slice(1)).get('invite'), name: 'Guest' }) })
  const cookie = joinResponse.headers.get('set-cookie').split(';')[0]
  const { lease } = await (await host('start', JSON.stringify({ jobStream: true }))).json()
  const { revision } = await (await host('scene', scene, lease)).json()
  data.root.matrix[12] = 8
  const raw = Buffer.from(encodeFrame(base, sceneChannels(data))), frame = gzipSync(raw), packet = Buffer.concat([Buffer.from(revision), frame])
  const control = join(root, 'control.json'); await writeFile(control, JSON.stringify({ url, token: app.controlToken }))
  const bridge = createShareBridge(process.execPath, [resolve('scripts/prepared_share_bridge.mjs'), control]); t.after(() => bridge.close())
  const sent = await bridge.request(`/host/shares/${share.id}/broadcast/frame`, { body: packet, headers: { 'X-NADOC-Broadcast': lease } })
  assert.equal(sent.status, 200)
  const endpoint = `${url}/meeting/${share.id}/live-frame?revision=${revision}&sequence=${sent.value.sequence}`
  assert.equal((await fetch(endpoint)).status, 401)
  assert.deepEqual(Buffer.from(await (await fetch(endpoint, { headers: { Cookie: cookie } })).arrayBuffer()), frame)
  await host('hold', undefined, lease)
  assert.equal((await fetch(endpoint, { headers: { Cookie: cookie } })).status, 200)
  const reset = await host('scene', scene, lease); assert.equal(reset.status, 200)
  const state = await (await fetch(`${url}/meeting/${share.id}/status`, { headers: { Cookie: cookie } })).json()
  assert.ok(state.presentation.liveFrame.sequence > sent.value.sequence)
  const caughtUp = await fetch(endpoint, { headers: { Cookie: cookie } })
  assert.equal(caughtUp.status, 200)
  assert.equal(Number(caughtUp.headers.get('X-NADOC-Sequence')), state.presentation.liveFrame.sequence)
  const obsolete = Buffer.concat([Buffer.from('f'.repeat(64)), frame])
  assert.equal((await host('frame', obsolete, lease)).status, 409)
  const progress = await bridge.request(`/host/shares/${share.id}/broadcast/progress`, { body: JSON.stringify({ fraction: .35 }), headers: { 'X-NADOC-Broadcast': lease } })
  assert.equal(progress.status, 200); assert.deepEqual(progress.value.loading, { fraction: .35 })
  assert.equal((await host('progress', JSON.stringify({ fraction: 9 }), lease)).status, 409)
  await host('pause', undefined, lease)
  assert.equal((await host('frame', packet, lease)).status, 409)
  assert.equal((await fetch(`${url}/meeting/${share.id}/scene`, { headers: { Cookie: cookie } })).status, 200)
  const events = await fetch(`${url}/meeting/${share.id}/events`, { headers: { Cookie: cookie } })
  const stream = events.text()
  await fetch(`${url}/host/stop`, { method: 'POST', headers: { Authorization: `Bearer ${app.controlToken}` } })
  const states = (await stream).split('\n').filter(line => line.startsWith('data: ')).map(line => JSON.parse(line.slice(6)))
  assert.equal(states.at(-1).ended, true); assert.equal(states.at(-1).presenting, false)
})
