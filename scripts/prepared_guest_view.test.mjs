import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createPreparedHost } from './prepared_view_host.mjs'
import { encodeContainer } from '../frontend/src/viewer/package_container.js'

test('guest one-shot endpoint requires its own session and origin and does not acquire presenter authority', async t => {
  const root = await mkdtemp(join(tmpdir(), 'nadoc-guest-camera-')); t.after(() => rm(root, { recursive: true, force: true }))
  await mkdir(join(root, 'assets')); await writeFile(join(root, 'viewer.html'), 'viewer')
  const app = await createPreparedHost({ dist: root }); t.after(() => app.stop())
  await new Promise(resolve => app.server.listen(0, '127.0.0.1', resolve))
  const url = `http://127.0.0.1:${app.server.address().port}`; app.setPublicBase(url)
  const share = app.createShare(Buffer.from(encodeContainer({ root: { children: [] }, geometries: [], materials: [] })))
  const base = `${url}/meeting/${share.id}`
  const joined = await fetch(`${base}/join`, { method: 'POST', headers: { Origin: url }, body: JSON.stringify({ token: new URLSearchParams(new URL(share.url).hash.slice(1)).get('invite'), name: 'Guest' }) })
  const cookie = joined.headers.get('set-cookie').split(';')[0], abort = new AbortController(); t.after(() => abort.abort())
  await fetch(`${base}/events`, { headers: { Cookie: cookie }, signal: abort.signal })
  const body = JSON.stringify({ revision: share.revision, camera: { position: [0, 0, 20], target: [0, 0, 0], up: [0, 1, 0], fov: 55, near: .1, far: 2000, orbitMode: 'orbit' } })
  assert.equal((await fetch(`${base}/share-view`, { method: 'POST', headers: { Origin: url }, body })).status, 403)
  assert.equal((await fetch(`${base}/share-view`, { method: 'POST', headers: { Origin: 'https://elsewhere.invalid', Cookie: cookie }, body })).status, 403)
  assert.equal((await fetch(`${base}/share-view`, { method: 'POST', headers: { Origin: url, Cookie: cookie }, body })).status, 200)
  const health = JSON.stringify({ networkSlow: true, renderSlow: true })
  assert.equal((await fetch(`${base}/health`, { method: 'POST', headers: { Origin: url }, body: health })).status, 403)
  assert.equal((await fetch(`${base}/health`, { method: 'POST', headers: { Origin: 'https://elsewhere.invalid', Cookie: cookie }, body: health })).status, 403)
  assert.equal((await fetch(`${base}/health`, { method: 'POST', headers: { Origin: url, Cookie: cookie }, body: health })).status, 200)
  const status = await (await fetch(`${base}/status`, { headers: { Cookie: cookie } })).json()
  assert.deepEqual(status.presentation.participants[0].health, { networkSlow: true, renderSlow: true })
  assert.equal(status.presentation.presenting, false); assert.equal(status.presentation.camera, null)
  assert.deepEqual(status.presentation.participants[0].sharedView.camera.position, [0, 0, 20])
  assert.equal((await fetch(`${base}/camera`, { method: 'POST', headers: { Origin: url, Cookie: cookie }, body })).status, 403)
})
