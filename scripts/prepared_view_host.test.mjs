import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createPreparedHost } from './prepared_view_host.mjs'

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
