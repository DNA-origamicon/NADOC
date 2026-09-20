// @vitest-environment node
import { afterEach, expect, it } from 'vitest'
import { createServer } from 'node:http'
import { EventEmitter } from 'node:events'
import { readFileSync, existsSync } from 'node:fs'
import { viewerTestPlugin, validateCommand, bridgeCredentialsPath, BRIDGE_PATH } from '../../viewer_test_server.js'

const disposers = []
afterEach(async () => { for (const dispose of disposers.splice(0)) await dispose() })
async function fixture() {
  const ws = new EventEmitter()
  const server = createServer()
  let build = 'first'
  viewerTestPlugin({ buildInfo: () => ({ frontend_sha256: build }) }).configureServer({
    config: { root: '/tmp/__nadoc_viewer_bridge_unit' }, ws, httpServer: server,
    middlewares: { use: handler => server.on('request', (req, res) => handler(req, res, () => { res.writeHead(404); res.end() })) },
  })
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const port = server.address().port
  const path = bridgeCredentialsPath('/tmp/__nadoc_viewer_bridge_unit', port)
  const { token } = JSON.parse(readFileSync(path))
  disposers.push(() => new Promise(resolve => server.close(() => { expect(existsSync(path)).toBe(false); resolve() })))
  const request = (route, options = {}) => fetch(`http://127.0.0.1:${port}${BRIDGE_PATH}${route}`, { ...options, headers: { Authorization: `Bearer ${token}`, ...options.headers } })
  const client = { socket: new EventEmitter(), send: (event, command) => { client.command = command } }
  ws.emit('nadoc:viewer-register', { id: 'viewer', status: { build: { frontend_sha256: 'first' } } }, client)
  return { ws, request, client, changeBuild: () => { build = 'second' }, command: value => request('/commands', { method: 'POST', body: JSON.stringify({ session: 'viewer', action: 'capture', options: { durationMs: 1000, variant: 'B' }, ...value }) }) }
}
it('rejects commands outside the bounded capture contract', () => {
  expect(() => validateCommand({ session: 'x', action: 'eval' })).toThrow()
  expect(() => validateCommand({ session: 'x', action: 'capture', options: { durationMs: 999999, variant: 'B' } })).toThrow()
  expect(validateCommand({ session: 'x', action: 'inspect', options: { code: 'anything' } })).toEqual({ session: 'x', action: 'inspect', options: {} })
})
it('requires controller authentication and rejects web page Origin requests', async () => {
  const f = await fixture()
  expect((await f.request('/sessions', { headers: { Authorization: 'wrong' } })).status).toBe(403)
  expect((await f.request('/sessions', { headers: { Origin: 'http://evil.example' } })).status).toBe(403)
  expect(await (await f.request('/sessions')).json()).toHaveLength(1)
})
it('correlates results to their socket, serializes commands, and rejects stale builds', async () => {
  const f = await fixture()
  const { id } = await (await f.command()).json()
  expect((await f.command()).status).toBe(409)
  f.ws.emit('nadoc:viewer-result', { id, result: 'spoof' }, { socket: {} })
  expect((await (await f.request(`/jobs/${id}`)).json()).status).toBe('running')
  f.ws.emit('nadoc:viewer-result', { id, result: { metrics: { valid: true } } }, f.client)
  expect((await (await f.request(`/jobs/${id}`)).json()).result.metrics.valid).toBe(true)
  f.changeBuild()
  expect((await f.command()).status).toBe(409)
})
it('fails pending work on disconnect and removes the session', async () => {
  const f = await fixture()
  const { id } = await (await f.command()).json()
  f.client.socket.emit('close')
  expect((await (await f.request(`/jobs/${id}`)).json()).error).toBe('Viewer disconnected')
  expect(await (await f.request('/sessions')).json()).toEqual([])
})

it('uses the same command isolation over the production browser event transport', async () => {
  const f = await fixture()
  const id = '00000000-0000-4000-8000-000000000001'
  const abort = new AbortController()
  try {
    const events = await f.request(`/browser-events?id=${id}`, { signal: abort.signal })
    expect(events.headers.get('content-type')).toBe('text/event-stream')
    const send = data => f.request('/browser-message', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
    expect((await send({ session: id, event: 'nadoc:viewer-register', data: { id, status: { build: { frontend_sha256: 'first' } } } })).status).toBe(200)
    const job = await (await f.command({ session: id })).json()
    await send({ session: id, event: 'nadoc:viewer-result', data: { id: job.id, result: { valid: true } } })
    expect((await (await f.request(`/jobs/${job.id}`)).json()).result.valid).toBe(true)
    expect((await send({ session: id, event: 'nadoc:viewer-command', data: {} })).status).toBe(400)
  } finally { abort.abort() }
})
