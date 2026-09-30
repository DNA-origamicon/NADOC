import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, mkdir, writeFile, rm, stat } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { createPreparedHost } from './prepared_view_host.mjs'

test('design invitations persist across starts and host restarts, isolate designs, and revoke credentials on reset', async t => {
  const root = await mkdtemp(join(tmpdir(), 'nadoc-design-links-'))
  t.after(() => rm(root, { recursive: true, force: true }))
  await mkdir(join(root, 'assets')); await writeFile(join(root, 'viewer.html'), 'viewer')
  const linksFile = join(root, 'links.json'), origin = 'https://present.example.test'
  let ready = false, clock = Date.now()
  async function start() {
    const host = await createPreparedHost({ dist: root, linksFile, publicOrigin: origin, persistent: true, lifetimeMs: 1000, now: () => clock, getPublicAccess: () => ({ state: ready ? 'ready' : 'unreachable' }) })
    t.after(host.stop)
    await new Promise(ok => host.server.listen(0, '127.0.0.1', ok))
    await new Promise(ok => host.controlServer.listen(0, '127.0.0.1', ok))
    const base = `http://127.0.0.1:${host.server.address().port}`, control = `http://127.0.0.1:${host.controlServer.address().port}`
    const admin = (path, method = 'POST', body, extra = {}) => fetch(control + '/host/' + path, { method, headers: { Authorization: `Bearer ${host.controlToken}`, ...extra }, body })
    return { host, base, admin, control }
  }
  let { host, base, admin, control } = await start()
  const allocate = (key, reset = false) => admin('links', 'POST', JSON.stringify({ key, reset })).then(r => r.json())
  const link = await allocate('part:alpha')
  assert.equal((await allocate('part:alpha')).url, link.url)
  assert.notEqual((await allocate('assembly:alpha')).id, link.id)
  assert.equal((await stat(linksFile)).mode & 0o777, 0o600)
  let endpoint = `${base}/meeting/${link.id}`
  const availability = () => fetch(endpoint + '/availability').then(r => r.json())
  assert.equal((await availability()).state, 'inactive')
  assert.equal((await fetch(endpoint + '/scene')).status, 410)
  assert.deepEqual((await (await admin('shares', 'GET')).json()).shares, [])
  await admin(`links/${link.id}/preparing`)
  assert.equal((await availability()).state, 'preparing')
  assert.equal((await admin('shares', 'POST', 'NADOCVW1before', { 'X-NADOC-Link': link.id })).status, 400)
  ready = true
  // Exercise the same constrained helper used by a WSL editor on Windows.
  const config = join(root, 'control.json'), body = join(root, 'request.bin')
  await writeFile(config, JSON.stringify({ url: control, token: host.controlToken }))
  const helper = async (path, contents, linkId = '') => {
    await writeFile(body, contents)
    const result = await promisify(execFile)(process.execPath, ['scripts/prepared_share_request.mjs', config, path, 'POST', body, '', '', linkId])
    return JSON.parse(result.stdout)
  }
  assert.equal((await helper('/host/links', JSON.stringify({ key: 'part:alpha' }))).value.url, link.url)
  const created = await helper('/host/shares', 'NADOCVW1before', link.id)
  assert.equal(created.status, 201)
  const active = created.value
  assert.equal(active.url, link.url); assert.equal(active.password, link.password)
  assert.equal((await availability()).state, 'active')
  const token = new URLSearchParams(new URL(link.url).hash.slice(1)).get('invite')
  const joinGuest = password => fetch(endpoint + '/join', { method: 'POST', headers: { Origin: origin }, body: JSON.stringify({ token, password, name: 'Guest' }) })
  assert.equal((await joinGuest('wrong')).status, 403)
  const joined = await joinGuest(link.password), cookie = joined.headers.get('set-cookie').split(';')[0]
  assert.equal(joined.status, 200)
  await admin(`shares/${link.id}`, 'DELETE')
  assert.equal((await availability()).state, 'inactive')
  assert.equal((await fetch(endpoint + '/scene', { headers: { Cookie: cookie } })).status, 410)
  assert.equal((await (await admin('shares', 'POST', 'NADOCVW1after', { 'X-NADOC-Link': link.id })).json()).url, link.url)
  assert.equal((await fetch(endpoint + '/scene', { headers: { Cookie: cookie } })).status, 401)
  clock += 2000
  assert.equal((await availability()).state, 'inactive')
  host.stop()
  ;({ host, base, admin } = await start()); endpoint = `${base}/meeting/${link.id}`
  assert.equal((await availability()).state, 'inactive')
  const restored = await allocate('part:alpha')
  assert.equal(restored.url, link.url); assert.equal(restored.qrUrl, link.qrUrl); assert.equal(restored.password, link.password)
  await admin('shares', 'POST', 'NADOCVW1restart', { 'X-NADOC-Link': link.id })
  const replacement = await allocate('part:alpha', true)
  assert.notEqual(replacement.id, link.id); assert.notEqual(replacement.password, link.password)
  assert.equal((await fetch(endpoint + '/availability')).status, 404)
  assert.equal((await fetch(endpoint + '/scene')).status, 410)
  assert.equal((await admin('shares', 'POST', 'NADOCVW1late', { 'X-NADOC-Link': link.id })).status, 404)
  assert.equal((await fetch(base + '/host/links', { method: 'POST', body: JSON.stringify({ key: 'part:steal' }) })).status, 404)
})

test('private invitation paths are stable per checkout and outside the static root', async () => {
  const { designLinksFile } = await import('./prepared_design_links.mjs')
  assert.equal(designLinksFile('/work/frontend/dist', '/user'), designLinksFile('/work/frontend/dist/', '/user'))
  assert.match(designLinksFile('/work/frontend/dist', '/user'), /^\/user\/\.nadoc\/presentation-links-[a-f0-9]{16}\.json$/)
  assert.notEqual(designLinksFile('/work/frontend/dist', '/user'), designLinksFile('/other/frontend/dist', '/user'))
})

test('concurrent allocation converges and a failed reset preserves the saved invitation', async t => {
  const { createDesignLinks } = await import('./prepared_design_links.mjs')
  const root = await mkdtemp(join(tmpdir(), 'nadoc-link-atomic-'))
  t.after(() => rm(root, { recursive: true, force: true }))
  const file = join(root, 'links.json'), links = await createDesignLinks(file)
  const [a, b] = await Promise.all([links.ensure('part:a'), links.ensure('part:a')])
  assert.equal(a.id, b.id)
  await mkdir(file + '.tmp') // force an atomic-write failure without changing file permissions
  await assert.rejects(links.ensure('part:a', true))
  assert.equal(links.get('part:a').id, a.id)
  assert.equal((await createDesignLinks(file)).get('part:a').id, a.id)
  await assert.rejects(links.ensure('invalid-key'))
})
