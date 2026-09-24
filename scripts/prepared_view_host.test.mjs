import { test } from 'node:test'
import assert from 'node:assert/strict'
import http from 'node:http'
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createPreparedHost } from './prepared_view_host.mjs'

test('local editor broadcasts update the existing invitation and guest cookie, with stale writes rejected', async t => {
  const root = await mkdtemp(join(tmpdir(), 'nadoc-editor-room-')); t.after(() => rm(root, { recursive: true, force: true }))
  await mkdir(join(root, 'assets')); await writeFile(join(root, 'viewer.html'), 'viewer')
  const host = await createPreparedHost({ dist: root }); t.after(host.stop)
  await new Promise(ok => host.server.listen(0, '127.0.0.1', ok))
  const base = `http://127.0.0.1:${host.server.address().port}`; host.setPublicBase(base)
  const share = host.createShare(Buffer.from('NADOCVW1before')), endpoint = `${base}/meeting/${share.id}`
  const auth = { Authorization: `Bearer ${host.controlToken}` }
  const joinResponse = await fetch(endpoint + '/join', { method: 'POST', headers: { Origin: base }, body: JSON.stringify({ name: 'Guest', token: new URLSearchParams(new URL(share.url).hash.slice(1)).get('invite') }) })
  const cookie = joinResponse.headers.get('set-cookie').split(';')[0]
  const route = `${base}/host/shares/${share.id}/broadcast/`
  assert.equal((await fetch(route + 'start', { method: 'POST', headers: { Cookie: cookie } })).status, 403)
  const started = await (await fetch(route + 'start', { method: 'POST', headers: auth })).json()
  const headers = { ...auth, 'X-NADOC-Broadcast': started.lease }
  const updated = await (await fetch(route + 'scene', { method: 'POST', headers, body: 'NADOCVW1after' })).json()
  assert.notEqual(updated.revision, share.revision)
  assert.equal((await fetch(endpoint + `/scene?revision=${share.revision}`, { headers: { Cookie: cookie } })).status, 409)
  assert.equal(await (await fetch(endpoint + `/scene?revision=${updated.revision}`, { headers: { Cookie: cookie } })).text(), 'NADOCVW1after')
  const status = await (await fetch(`${base}/host/shares`, { headers: auth })).json()
  assert.equal(status.shares[0].url, share.url); assert.equal(status.shares[0].presenterUrl, share.presenterUrl)
  assert.ok(status.capabilities.includes('editor-broadcast-v1'))
  assert.equal((await fetch(route + 'pause', { method: 'POST', headers })).status, 200)
  assert.equal((await fetch(route + 'scene', { method: 'POST', headers, body: 'NADOCVW1private' })).status, 409)
  assert.equal(await (await fetch(endpoint + '/scene', { headers: { Cookie: cookie } })).text(), 'NADOCVW1after')
})

test('only the presenter can publish; late guests receive the latest snapshot-bound camera', async t => {
  const root = await mkdtemp(join(tmpdir(), 'nadoc-room-test-')); t.after(() => rm(root, { recursive: true, force: true }))
  await mkdir(join(root, 'assets')); await writeFile(join(root, 'viewer.html'), 'viewer')
  let now = Date.now()
  const host = await createPreparedHost({ dist: root, now: () => now }); t.after(host.stop)
  await new Promise(ok => host.server.listen(0, '127.0.0.1', ok))
  const base = `http://127.0.0.1:${host.server.address().port}`; host.setPublicBase(base)
  const share = host.createShare(Buffer.from('NADOCVW1room')), endpoint = base + `/meeting/${share.id}`
  const joinRoom = (url, role = 'guest') => fetch(endpoint + '/join', { method: 'POST', headers: { Origin: base }, body: JSON.stringify({ token: new URLSearchParams(new URL(url).hash.slice(1)).get('invite'), role, name: role }) })
  assert.equal((await joinRoom(share.url, 'presenter')).status, 403)
  const presenter = await joinRoom(share.presenterUrl, 'presenter'), guest = await joinRoom(share.url)
  const pc = presenter.headers.get('set-cookie').split(';')[0], gc = guest.headers.get('set-cookie').split(';')[0]
  assert.equal((await presenter.json()).role, 'presenter')
  assert.equal((await joinRoom(share.presenterUrl, 'presenter')).status, 409)
  const camera = { position: [10, 0, 30], target: [0, 0, 0], up: [0, 1, 0], fov: 55, near: .1, far: 2000, orbitMode: 'orbit' }
  const post = (cookie, revision = share.revision) => fetch(endpoint + '/camera', { method: 'POST', headers: { Origin: base, Cookie: cookie }, body: JSON.stringify({ revision, camera }) })
  assert.equal((await post(gc)).status, 403)
  assert.equal((await post(pc, 'other')).status, 400)
  assert.equal((await post(pc)).status, 200)
  assert.equal((await fetch(endpoint + '/events')).status, 401)
  const stream = await fetch(endpoint + '/events', { headers: { Cookie: gc } }), reader = stream.body.getReader()
  const first = new TextDecoder().decode((await reader.read()).value)
  assert.match(first, /"sequence":1/); assert.match(first, /"position":\[10,0,30\]/)
  assert.ok(!first.includes(new URL(share.presenterUrl).hash)); assert.ok(!first.includes('presenterToken'))
  await fetch(endpoint + '/pause', { method: 'POST', headers: { Origin: base, Cookie: pc } })
  assert.match(new TextDecoder().decode((await reader.read()).value), /"presenting":false/)
  await reader.cancel()
  await joinRoom(share.url); await joinRoom(share.url)
  assert.equal((await joinRoom(share.url)).status, 409)
  const second = host.createShare(Buffer.from('NADOCVW1second'))
  const joinOther = () => fetch(base + `/meeting/${second.id}/join`, { method: 'POST', headers: { Origin: base }, body: JSON.stringify({ token: new URLSearchParams(new URL(second.url).hash.slice(1)).get('invite'), name: 'Other room' }) })
  assert.equal((await joinOther()).status, 409) // limit is across snapshots
  now += 120001
  assert.equal((await joinOther()).status, 200) // disconnected leases are reclaimed
  const resume = (cookie, url, role) => fetch(endpoint + '/join', { method: 'POST', headers: { Origin: base, Cookie: cookie }, body: JSON.stringify({ resume: true, role, token: new URLSearchParams(new URL(url).hash.slice(1)).get('invite') }) })
  assert.equal((await resume(pc, share.presenterUrl, 'presenter')).status, 200) // presenter identity survives absence
  const fresh = await joinRoom(share.url), freshCookie = fresh.headers.get('set-cookie').split(';')[0]
  assert.equal((await resume(freshCookie, share.presenterUrl, 'presenter')).status, 401)
  assert.equal((await resume(pc, share.url, 'guest')).status, 401)
  assert.equal((await post(pc)).status, 200)
  await joinRoom(share.url) // four slots occupied, including the retained presenter
  assert.equal((await fetch(endpoint + '/leave', { method: 'POST', headers: { Origin: base, Cookie: freshCookie } })).status, 403)
  assert.equal((await fetch(endpoint + '/leave', { method: 'POST', headers: { Origin: base, Cookie: pc } })).status, 200)
  assert.equal((await joinRoom(share.url)).status, 409) // the host can still return to a full room
  assert.equal((await post(pc)).status, 403)
  const away = await (await fetch(endpoint + '/status', { headers: { Cookie: freshCookie } })).json()
  assert.equal(away.presentation.presenting, false)
  assert.equal((await fetch(endpoint + '/scene', { headers: { Cookie: freshCookie } })).status, 200)
  assert.equal((await resume(pc, share.presenterUrl, 'presenter')).status, 200)
  assert.equal((await post(pc)).status, 200)
  assert.equal((await resume(freshCookie, share.url, 'guest')).status, 200)
  assert.equal((await fetch(endpoint + '/scene', { headers: { Cookie: freshCookie } })).status, 200)
  const arrived = new Promise(ok => host.server.once('request', ok))
  let finishCamera
  const delayedCamera = new Promise((ok, fail) => {
    const request = http.request(endpoint + '/camera', { method: 'POST', headers: { Origin: base, Cookie: pc } }, response => {
      response.resume(); response.once('end', () => ok(response.statusCode))
    })
    request.on('error', fail); request.write('{"revision":')
    finishCamera = () => request.end(JSON.stringify(share.revision) + ',"camera":' + JSON.stringify(camera) + '}')
  })
  await arrived
  await fetch(endpoint + '/leave', { method: 'POST', headers: { Origin: base, Cookie: pc } })
  assert.equal((await resume(pc, share.presenterUrl, 'presenter')).status, 200)
  finishCamera(); assert.equal(await delayedCamera, 403) // even after Return, a request started before Leave cannot restart broadcasting
  assert.equal((await (await fetch(endpoint + '/status', { headers: { Cookie: freshCookie } })).json()).presentation.presenting, false)
  await fetch(endpoint + '/leave', { method: 'POST', headers: { Origin: base, Cookie: pc } })
  assert.equal((await joinRoom(share.presenterUrl, 'presenter')).status, 200) // authenticated return from another browser
  assert.equal((await resume(pc, share.presenterUrl, 'presenter')).status, 401) // old presenter authority is replaced
  assert.equal((await fetch(endpoint + '/scene', { headers: { Cookie: freshCookie } })).status, 200)
})

test('internet guests require the password and HTTPS origin; management is on a separate listener', async t => {
  const root = await mkdtemp(join(tmpdir(), 'nadoc-host-test-')); t.after(() => rm(root, { recursive: true, force: true }))
  await mkdir(join(root, 'assets')); await writeFile(join(root, 'viewer.html'), 'viewer')
  const publicOrigin = 'https://meeting.example', host = await createPreparedHost({ dist: root, publicOrigin }); t.after(host.stop)
  await new Promise(ok => host.server.listen(0, '127.0.0.1', ok))
  await new Promise(ok => host.controlServer.listen(0, '127.0.0.1', ok))
  const base = `http://127.0.0.1:${host.server.address().port}`, control = `http://127.0.0.1:${host.controlServer.address().port}`
  const auth = { Authorization: `Bearer ${host.controlToken}` }
  const created = await fetch(control + '/host/shares', { method: 'POST', headers: auth, body: 'NADOCVW1internet' })
  const share = await created.json(), params = new URLSearchParams(new URL(share.url).hash.slice(1))
  assert.equal(created.status, 201); assert.equal(new URL(share.url).origin, publicOrigin)
  assert.ok(share.password.length >= 16); assert.ok(!share.url.includes(share.password))
  for (const path of ['/host/shares', '/host/stop', '/api/design']) assert.equal((await fetch(base + path, { headers: auth })).status, 404)
  const endpoint = `/meeting/${share.id}`
  const joinRoom = (password, origin = publicOrigin) => fetch(base + endpoint + '/join', { method: 'POST', headers: { Origin: origin }, body: JSON.stringify({ name: 'Guest', token: params.get('invite'), password }) })
  assert.equal((await joinRoom(undefined)).status, 403)
  assert.equal((await joinRoom('incorrect')).status, 403)
  assert.equal((await joinRoom(share.password, base)).status, 403)
  assert.equal((await joinRoom(share.password, 'https://evil.example')).status, 403)
  assert.equal((await fetch(base + endpoint + '/scene')).status, 401)
  const joined = await joinRoom(share.password), cookie = joined.headers.get('set-cookie')
  assert.equal(joined.status, 200); assert.match(cookie, /; Secure/)
  const scene = await fetch(base + endpoint + '/scene', { headers: { Cookie: cookie.split(';')[0] } })
  assert.equal(await scene.text(), 'NADOCVW1internet')
  assert.equal((await fetch(control + '/viewer.html')).status, 404)
  for (let i = 0; i < 60; i++) await joinRoom('incorrect')
  assert.equal((await joinRoom('incorrect')).status, 429)
  host.stop(); await assert.rejects(fetch(control + '/host/shares', { headers: auth }))
})

test('invite, session limit, exact file surface, expiry and stop protect the package', async t => {
  const root = await mkdtemp(join(tmpdir(), 'nadoc-host-test-'))
  t.after(() => rm(root, { recursive: true, force: true }))
  await mkdir(join(root, 'assets'))
  await writeFile(join(root, 'viewer.html'), '<h1>Viewer</h1>')
  await writeFile(join(root, 'assets/viewer.js'), 'export {}')
  await writeFile(join(root, 'secret.txt'), 'must not be served')
  await writeFile(join(root, 'scene.nadocview'), 'NADOCVW1test')
  let clock = 1000
  const host = await createPreparedHost({ dist: root, packagePath: join(root, 'scene.nadocview'), lifetimeMs: 10000, now: () => clock })
  t.after(host.stop)
  await new Promise(resolve => host.server.listen(0, '127.0.0.1', resolve))
  const base = `http://127.0.0.1:${host.server.address().port}`
  const get = (path, cookie) => fetch(base + path, { headers: cookie ? { Cookie: cookie } : {} })
  const joinView = (token, name, origin = base, cookie = '') => fetch(base + '/meeting/join', { method: 'POST', headers: { Origin: origin, Cookie: cookie, 'Content-Type': 'application/json' }, body: JSON.stringify({ token, name }) })
  assert.equal((await get('/viewer.html')).status, 200)
  assert.equal((await get('/assets/viewer.js')).status, 200)
  for (const path of ['/secret.txt', '/scene.nadocview', '/api/design', '/assets/../secret.txt', '/assets/%2e%2e/secret.txt']) assert.equal((await get(path)).status, 404)
  assert.equal((await get('/meeting/scene')).status, 401)
  assert.equal((await joinView('bad', 'Alice')).status, 403)
  assert.equal((await joinView(host.invite, 'Alice', 'http://elsewhere')).status, 403)
  assert.equal((await joinView(host.invite, ' ')).status, 400)
  const joined = await joinView(host.invite, 'Alice')
  assert.equal(joined.status, 200)
  const cookie = joined.headers.get('set-cookie').split(';')[0]
  assert.match(joined.headers.get('set-cookie'), /HttpOnly; SameSite=Strict/)
  assert.equal((await (await get('/meeting/status', cookie)).json()).name, 'Alice')
  const scene = await get('/meeting/scene', cookie)
  assert.equal(scene.headers.get('cache-control'), 'no-store')
  assert.equal(await scene.text(), 'NADOCVW1test')
  for (const name of ['B', 'C', 'D']) assert.equal((await joinView(host.invite, name)).status, 200)
  assert.equal((await joinView(host.invite, 'E')).status, 409)
  assert.equal((await joinView(host.invite, 'Alice', base, cookie)).status, 200)
  clock = 11000
  assert.equal((await get('/meeting/scene', cookie)).status, 410)
  assert.equal((await joinView(host.invite, 'Alice')).status, 410)
  host.stop()
  await assert.rejects(get('/viewer.html'))
})

test('part-specific links isolate snapshots and cookies and revoke independently', async t => {
  const root = await mkdtemp(join(tmpdir(), 'nadoc-host-test-')); t.after(() => rm(root, { recursive: true, force: true }))
  await mkdir(join(root, 'assets')); await writeFile(join(root, 'viewer.html'), 'viewer')
  const host = await createPreparedHost({ dist: root }); t.after(host.stop)
  await new Promise(resolve => host.server.listen(0, '127.0.0.1', resolve))
  const base = `http://127.0.0.1:${host.server.address().port}`; host.setPublicBase(base)
  const auth = { Authorization: `Bearer ${host.controlToken}` }
  assert.equal((await fetch(base + '/host/shares')).status, 403)
  assert.equal((await fetch(base + '/host/shares', { headers: { ...auth, Origin: base } })).status, 403)
  const create = title => fetch(base + '/host/shares', { method: 'POST', headers: { ...auth, 'X-NADOC-Title': encodeURIComponent(title) }, body: 'NADOCVW1' + title }).then(r => r.json())
  const a = await create('Part A'), b = await create('Part B')
  assert.notEqual(a.url, b.url); assert.equal(a.title, 'Part A')
  const joinRoom = (share, token) => fetch(base + `/meeting/${share.id}/join`, { method: 'POST', headers: { Origin: base }, body: JSON.stringify({ token: token ?? new URLSearchParams(new URL(share.url).hash.slice(1)).get('invite'), name: 'Test guest' }) })
  const aj = await joinRoom(a), bj = await joinRoom(b)
  const ac = aj.headers.get('set-cookie').split(';')[0], bc = bj.headers.get('set-cookie').split(';')[0]
  assert.notEqual(ac.split('=')[0], bc.split('=')[0])
  assert.equal((await fetch(base + `/meeting/${b.id}/scene`, { headers: { Cookie: ac } })).status, 401)
  assert.equal((await joinRoom(b, new URLSearchParams(new URL(a.url).hash.slice(1)).get('invite'))).status, 403)
  assert.equal(await (await fetch(base + `/meeting/${a.id}/scene`, { headers: { Cookie: ac + '; ' + bc } })).text(), 'NADOCVW1Part A')
  assert.equal((await fetch(base + `/host/shares/${a.id}`, { method: 'DELETE', headers: auth })).status, 200)
  assert.equal((await fetch(base + `/meeting/${a.id}/scene`, { headers: { Cookie: ac } })).status, 410)
  assert.equal(await (await fetch(base + `/meeting/${b.id}/scene`, { headers: { Cookie: bc } })).text(), 'NADOCVW1Part B')
})

test('reauthentication rotates cookies, revokes old streams, and bounds streams per session', async t => {
  const root = await mkdtemp(join(tmpdir(), 'nadoc-session-audit-')); t.after(() => rm(root, { recursive: true, force: true }))
  await mkdir(join(root, 'assets')); await writeFile(join(root, 'viewer.html'), 'viewer')
  const host = await createPreparedHost({ dist: root }); t.after(host.stop)
  await new Promise(ok => host.server.listen(0, '127.0.0.1', ok))
  const base = `http://127.0.0.1:${host.server.address().port}`; host.setPublicBase(base)
  const share = host.createShare(Buffer.from('NADOCVW1session')), endpoint = `${base}/meeting/${share.id}`
  const joinRoom = (url, role = 'guest', cookie = '') => fetch(endpoint + '/join', { method: 'POST', headers: { Origin: base, Cookie: cookie },
    body: JSON.stringify({ role, name: role, token: new URLSearchParams(new URL(url).hash.slice(1)).get('invite') }) })
  const cookie = response => response.headers.get('set-cookie').split(';')[0]
  const guest = cookie(await joinRoom(share.url))
  const streams = []
  for (let i = 0; i < 2; i++) {
    const response = await fetch(endpoint + '/events', { headers: { Cookie: guest } })
    assert.equal(response.status, 200)
    const reader = response.body.getReader(); await reader.read(); streams.push(reader)
  }
  assert.equal((await fetch(endpoint + '/events', { headers: { Cookie: guest } })).status, 429)
  // One guest cannot consume every room slot.
  const other = cookie(await joinRoom(share.url))
  const response = await fetch(endpoint + '/events', { headers: { Cookie: other } })
  assert.equal(response.status, 200); await response.body.cancel()
  const presenter = cookie(await joinRoom(share.presenterUrl, 'presenter', guest))
  assert.notEqual(presenter, guest)
  assert.equal((await fetch(endpoint + '/scene', { headers: { Cookie: guest } })).status, 401)
  for (const reader of streams) { while (!(await reader.read()).done) { /* drain queued presence */ } }
  assert.equal((await (await fetch(endpoint + '/status', { headers: { Cookie: presenter } })).json()).role, 'presenter')
  const rejoined = cookie(await joinRoom(share.presenterUrl, 'presenter', presenter))
  assert.notEqual(rejoined, presenter)
  assert.equal((await fetch(endpoint + '/status', { headers: { Cookie: presenter } })).status, 401)
  assert.equal((await fetch(endpoint + '/status', { headers: { Cookie: rejoined } })).status, 200)
})

test('host expiry closes an already authenticated event stream without another request', async t => {
  const root = await mkdtemp(join(tmpdir(), 'nadoc-expiry-audit-')); t.after(() => rm(root, { recursive: true, force: true }))
  await mkdir(join(root, 'assets')); await writeFile(join(root, 'viewer.html'), 'viewer')
  let clock = 1000
  const host = await createPreparedHost({ dist: root, lifetimeMs: 1000, now: () => clock }); t.after(host.stop)
  await new Promise(ok => host.server.listen(0, '127.0.0.1', ok))
  const base = `http://127.0.0.1:${host.server.address().port}`; host.setPublicBase(base)
  const share = host.createShare(Buffer.from('NADOCVW1expiry')), endpoint = `${base}/meeting/${share.id}`
  const joined = await fetch(endpoint + '/join', { method: 'POST', headers: { Origin: base }, body: JSON.stringify({ name: 'Guest', token: new URLSearchParams(new URL(share.url).hash.slice(1)).get('invite') }) })
  const cookie = joined.headers.get('set-cookie').split(';')[0]
  const response = await fetch(endpoint + '/events', { headers: { Cookie: cookie }, signal: AbortSignal.timeout(5000) })
  const reader = response.body.getReader(); await reader.read()
  clock = 2001
  let remaining = ''
  for (;;) { const chunk = await reader.read(); if (chunk.done) break; remaining += new TextDecoder().decode(chunk.value) }
  assert.match(remaining, /"ended":true/)
})
