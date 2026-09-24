import { test } from 'node:test'
import assert from 'node:assert/strict'
import http from 'node:http'
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createPreparedHost } from '../scripts/prepared_view_host.mjs'
import { preparedSharePlugin } from './prepared_share_server.js'

test('a failed bootstrap is recovered only when the authenticated host responds', async t => {
  const root = await mkdtemp(join(tmpdir(), 'nadoc-share-start-')); t.after(() => rm(root, { recursive: true, force: true }))
  const controlFile = join(root, 'host.json')
  let handler, ready = true, launches = 0, requests = 0
  const editor = http.createServer((req, res) => handler(req, res, () => res.end())); t.after(() => { editor.close(); editor.closeAllConnections() })
  await new Promise(ok => editor.listen(0, '127.0.0.1', ok))
  preparedSharePlugin({ controlFile, launch: async () => {
    launches++
    await writeFile(controlFile, JSON.stringify({ url: 'http://127.0.0.1:5184', token: 'a'.repeat(64) }))
    await writeFile(controlFile + '.status.json', JSON.stringify({ state: 'ready' }))
    throw new Error('Bootstrap timed out')
  }, transport: async () => { requests++; if (!ready) throw new Error('Host unavailable'); return { shares: [], capabilities: ['live-unlimited-frames-v1'] } } }).configureServer({ config: { root }, httpServer: editor, middlewares: { use: fn => { handler = fn } } })
  const start = () => fetch(`http://127.0.0.1:${editor.address().port}/__nadoc_share/start`, { method: 'POST', headers: { 'X-NADOC-Share': '1' } })
  assert.equal((await start()).status, 200)
  assert.equal(launches, 1); assert.equal(requests, 1)
  assert.equal((await start()).status, 200); assert.equal(launches, 1)
  ready = false
  const failed = await start(); assert.equal(failed.status, 503)
  assert.deepEqual(await failed.json(), { error: 'Bootstrap timed out' })
  assert.equal(launches, 2)
})
test('editor middleware keeps host credentials local and publishes only from the local same-origin editor', async t => {
  const root = await mkdtemp(join(tmpdir(), 'nadoc-share-server-')); t.after(() => rm(root, { recursive: true, force: true }))
  await mkdir(join(root, 'assets')); await writeFile(join(root, 'viewer.html'), 'viewer')
  const host = await createPreparedHost({ dist: root }); t.after(host.stop)
  await new Promise(ok => host.server.listen(0, '127.0.0.1', ok))
  const hostUrl = `http://127.0.0.1:${host.server.address().port}`; host.setPublicBase(hostUrl)
  const controlFile = join(root, 'host.json')
  let handler, launches = 0
  const editor = http.createServer((req, res) => handler(req, res, () => { res.writeHead(404); res.end() })); t.after(() => { editor.close(); editor.closeAllConnections() })
  await new Promise(ok => editor.listen(0, '127.0.0.1', ok))
  preparedSharePlugin({ controlFile, transport: async ({ config, path, options }) => { const response = await fetch(config.url + path, { ...options, headers: { ...options.headers, Authorization: `Bearer ${config.token}` } }); const result = await response.json(); if (!response.ok) throw new Error(result.error); return result }, launch: async () => { launches++ } }).configureServer({ config: { root }, httpServer: editor, middlewares: { use: fn => { handler = fn } } })
  const base = `http://127.0.0.1:${editor.address().port}`, headers = { 'X-NADOC-Share': '1', Origin: base }
  await fetch(base + '/__nadoc_share/status') // startup finds no detached host
  await writeFile(controlFile, JSON.stringify({ url: hostUrl, token: host.controlToken }))
  const create = options => fetch(base + '/__nadoc_share/create', { method: 'POST', body: 'NADOCVW1test', ...options })
  assert.equal((await create()).status, 403)
  assert.equal((await create({ headers: { ...headers, Origin: 'http://evil.example' } })).status, 403)
  const badHost = await new Promise((ok, fail) => { const req = http.request(base + '/__nadoc_share/create', { method: 'POST', headers: { ...headers, Host: 'evil.example' } }, res => { res.resume(); ok(res.statusCode) }); req.on('error', fail); req.end('NADOCVW1test') }); assert.equal(badHost, 403)
  const start = await fetch(base + '/__nadoc_share/start', { method: 'POST', headers }); assert.equal(start.status, 200); assert.equal(launches, 0)
  const published = await create({ headers: { ...headers, 'X-NADOC-Title': 'Part%20A' } }); assert.equal(published.status, 201)
  const share = await published.json(); assert.equal(share.title, 'Part A'); assert.match(share.url, /#room=/)
  const status = await (await fetch(base + '/__nadoc_share/status')).text(); assert.ok(!status.includes(host.controlToken)); assert.match(status, /Part A/)
  assert.equal((await fetch(base + `/__nadoc_share/shares/${share.id}`, { method: 'DELETE', headers })).status, 200)
  assert.deepEqual((await (await fetch(base + '/__nadoc_share/status')).json()).shares, [])
})

test('server startup and shutdown revoke invitations left in the detached host', async t => {
  const root = await mkdtemp(join(tmpdir(), 'nadoc-share-lifecycle-')); t.after(() => rm(root, { recursive: true, force: true }))
  await mkdir(join(root, 'assets')); await writeFile(join(root, 'viewer.html'), 'viewer')
  const host = await createPreparedHost({ dist: root }); t.after(host.stop)
  await new Promise(ok => host.server.listen(0, '127.0.0.1', ok))
  const url = `http://127.0.0.1:${host.server.address().port}`; host.setPublicBase(url)
  const controlFile = join(root, 'host.json'); await writeFile(controlFile, JSON.stringify({ url, token: host.controlToken }))
  const old = host.createShare(Buffer.from('NADOCVW1old'))
  const transport = async ({ config, path, options }) => {
    const response = await fetch(config.url + path, { ...options, headers: { Authorization: `Bearer ${config.token}` } })
    if (!response.ok) throw new Error('Host failed')
    return response.json()
  }
  let handler
  const editor = http.createServer((req, res) => handler(req, res, () => res.end()))
  t.after(() => { editor.close(); editor.closeAllConnections() })
  preparedSharePlugin({ controlFile, transport }).configureServer({ config: { root }, httpServer: editor, middlewares: { use: fn => { handler = fn } } })
  await new Promise(ok => editor.listen(0, '127.0.0.1', ok))
  await fetch(`http://127.0.0.1:${editor.address().port}/__nadoc_share/status`)
  await assert.rejects(fetch(`${url}/meeting/${old.id}/status`))
  const live = await createPreparedHost({ dist: root }); t.after(live.stop)
  await new Promise(ok => live.server.listen(0, '127.0.0.1', ok))
  const liveUrl = `http://127.0.0.1:${live.server.address().port}`; live.setPublicBase(liveUrl)
  await writeFile(controlFile, JSON.stringify({ url: liveUrl, token: live.controlToken }))
  const active = live.createShare(Buffer.from('NADOCVW1current'))
  await new Promise(ok => editor.close(ok)); editor.closeAllConnections()
  for (let i = 0; i < 100; i++) {
    try { await fetch(`${liveUrl}/meeting/${active.id}/status`) } catch { return }
    await new Promise(ok => setTimeout(ok, 10))
  }
  assert.fail('Detached host survived editor shutdown')
})

test('a stale detached build is stopped and replaced before starting another invitation', async t => {
  const root = await mkdtemp(join(tmpdir(), 'nadoc-share-upgrade-')); t.after(() => rm(root, { recursive: true, force: true }))
  const controlFile = join(root, 'host.json')
  let handler, ready = true, buildId = 'old', launches = 0, stops = 0
  const editor = http.createServer((req, res) => handler(req, res, () => res.end()))
  t.after(() => { editor.close(); editor.closeAllConnections() })
  await new Promise(ok => editor.listen(0, '127.0.0.1', ok))
  preparedSharePlugin({ controlFile, getBuildId: async () => 'current',
    transport: async ({ path }) => {
      if (!ready) throw new Error('Stopped')
      if (path === '/host/stop') { stops++; ready = false; return {} }
      return { shares: [], capabilities: ['live-unlimited-frames-v1'], buildId }
    }, launch: async () => { launches++; ready = true; buildId = 'current' },
  }).configureServer({ config: { root }, httpServer: editor, middlewares: { use: fn => { handler = fn } } })
  const base = `http://127.0.0.1:${editor.address().port}/__nadoc_share`
  await fetch(base + '/status')
  await writeFile(controlFile, JSON.stringify({ url: 'http://127.0.0.1:5184', token: 'a'.repeat(64) }))
  assert.equal((await (await fetch(base + '/status')).json()).updateRequired, true)
  const options = { method: 'POST', headers: { 'X-NADOC-Share': '1' } }
  const responses = await Promise.all([fetch(base + '/start', options), fetch(base + '/start', options)])
  for (const response of responses) { assert.equal(response.status, 200); assert.equal((await response.json()).buildId, 'current') }
  assert.equal(stops, 1); assert.equal(launches, 1)
  assert.equal((await (await fetch(base + '/status')).json()).updateRequired, false)
})

test('only the configured private editor origin can publish through loopback', async t => {
  let handler
  const root = await mkdtemp(join(tmpdir(), 'nadoc-share-origin-'))
  t.after(() => rm(root, { recursive: true, force: true }))
  const server = http.createServer((req, res) => handler(req, res, () => res.end()))
  t.after(() => { server.close(); server.closeAllConnections() })
  await new Promise(ok => server.listen(0, '127.0.0.1', ok))
  preparedSharePlugin({ publicUrl: 'https://this.example.ts.net:5173', controlFile: join(root, 'missing') })
    .configureServer({ config: { root }, httpServer: server, middlewares: { use: fn => { handler = fn } } })
  const get = headers => new Promise((ok, fail) => {
    const req = http.request({ host: '127.0.0.1', port: server.address().port, path: '/__nadoc_share/status', headers }, res => { res.resume(); ok(res.statusCode) })
    req.on('error', fail); req.end()
  })
  assert.equal(await get({ Host: 'this.example.ts.net:5173', Origin: 'https://this.example.ts.net:5173' }), 200)
  assert.equal(await get({ Host: 'other.example.ts.net:5173', Origin: 'https://other.example.ts.net:5173' }), 403)
  assert.equal(await get({ Host: 'this.example.ts.net:5173', Origin: 'https://evil.example' }), 403)
  assert.equal(await get({ Host: 'this.example.ts.net:5173', 'Sec-Fetch-Site': 'cross-site' }), 403)
})
