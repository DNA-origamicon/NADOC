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
  }, transport: async () => { requests++; if (!ready) throw new Error('Host unavailable'); return { shares: [] } } }).configureServer({ config: { root }, httpServer: editor, middlewares: { use: fn => { handler = fn } } })
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
  const controlFile = join(root, 'host.json'); await writeFile(controlFile, JSON.stringify({ url: hostUrl, token: host.controlToken }))
  let handler, launches = 0
  const editor = http.createServer((req, res) => handler(req, res, () => { res.writeHead(404); res.end() })); t.after(() => { editor.close(); editor.closeAllConnections() })
  await new Promise(ok => editor.listen(0, '127.0.0.1', ok))
  preparedSharePlugin({ controlFile, transport: async ({ config, path, options }) => { const response = await fetch(config.url + path, { ...options, headers: { ...options.headers, Authorization: `Bearer ${config.token}` } }); const result = await response.json(); if (!response.ok) throw new Error(result.error); return result }, launch: async () => { launches++ } }).configureServer({ config: { root }, httpServer: editor, middlewares: { use: fn => { handler = fn } } })
  const base = `http://127.0.0.1:${editor.address().port}`, headers = { 'X-NADOC-Share': '1', Origin: base }
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
