import { randomBytes, randomUUID, createHash } from 'node:crypto'
import { writeFileSync, unlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { EventEmitter } from 'node:events'
import { frontendBuildInfo } from './build_info.js'
import { viewerFilePath } from './src/perf/viewer_file_open.js'
import { viewerTestDestination } from './src/perf/viewer_test_transport.js'

export const BRIDGE_PATH = '/__nadoc_viewer_test'
export function bridgeCredentialsPath(root, port) {
  return join(tmpdir(), `nadoc-viewer-test-${createHash('sha256').update(root).digest('hex').slice(0, 12)}-${port}.json`)
}

export function validateCommand(value) {
  if (!value || typeof value.session !== 'string' || !['inspect', 'snapshot', 'capture', 'open', 'visit'].includes(value.action)) throw new Error('Choose a session and inspect, snapshot, capture, open, or visit')
  const options = value.options ?? {}
  if (value.action === 'visit') return { session: value.session, action: 'visit', options: { url: viewerTestDestination(options.url) } }
  if (value.action === 'open') return { session: value.session, action: 'open', options: { path: viewerFilePath(options.path) } }
  if (value.action === 'capture') {
    if (!Number.isFinite(options.durationMs) || options.durationMs < 1000 || options.durationMs > 60000) throw new Error('Capture duration must be 1–60 seconds')
    if (!['A', 'B'].includes(options.variant)) throw new Error('Capture variant must be A or B')
  }
  return { session: value.session, action: value.action, options: value.action === 'capture' ? { durationMs: options.durationMs, variant: options.variant, scenario: 'orbit' } : {} }
}

/** Local benchmark control plane. No arbitrary JS execution. */
export function viewerTestPlugin({ buildInfo = frontendBuildInfo } = {}) {
  function configure(server) {
      const token = randomBytes(32).toString('hex')
      const sessions = new Map(), jobs = new Map()
      const browserClients = new Map()
      let credentialsFile
      const json = (res, status, value) => {
        res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' })
        res.end(JSON.stringify(value))
      }
      function failPending(session, message) {
        for (const job of jobs.values()) if (job.session === session && job.status === 'running') {
          job.status = 'error'; job.error = message; clearTimeout(job.timer)
        }
      }
      function register(data, client) {
        if (!data || typeof data.id !== 'string' || data.id.length > 100) return
        for (const [id, entry] of sessions) if (entry.client === client && id !== data.id) {
          failPending(id, 'Viewer reloaded'); sessions.delete(id)
        }
        if (sessions.has(data.id) && sessions.get(data.id).client !== client) return
        sessions.set(data.id, { client, info: { id: data.id, status: data.status, connected_at: new Date().toISOString() } })
        client.socket.once('close', () => {
          if (sessions.get(data.id)?.client !== client) return
          failPending(data.id, 'Viewer disconnected'); sessions.delete(data.id)
        })
      }
      function result(data, client) {
        const job = jobs.get(data?.id)
        if (!job || job.status !== 'running' || sessions.get(job.session)?.client !== client) return
        clearTimeout(job.timer)
        job.status = data.error ? 'error' : 'completed'
        job.error = data.error
        job.result = data.result
        job.finished_at = new Date().toISOString()
      }
      server.ws?.on('nadoc:viewer-register', register)
      server.ws?.on('nadoc:viewer-result', result)
      async function body(req, limit) {
        let text = ''
        for await (const chunk of req) { text += chunk; if (text.length > limit) throw new Error('Request too large') }
        return JSON.parse(text)
      }
      server.middlewares.use(async (req, res, next) => {
        const url = new URL(req.url, 'http://localhost')
        if (!url.pathname.startsWith(BRIDGE_PATH)) return next()
        if (url.pathname.startsWith(`${BRIDGE_PATH}/browser-`)) {
          // Browser messages can only register/answer for their own random SSE
          // session. They never submit controller commands or obtain its key.
          if (req.headers['sec-fetch-site'] === 'cross-site' ||
              (req.headers.origin && req.headers.origin !== `http://${req.headers.host}`)) return json(res, 403, { error: 'Same-origin browser connection required' })
          try {
            if (req.method === 'GET' && url.pathname === `${BRIDGE_PATH}/browser-events`) {
              const id = url.searchParams.get('id')
              if (!/^[a-f0-9-]{36}$/.test(id ?? '') || browserClients.has(id) || browserClients.size >= 8) return json(res, 400, { error: 'Invalid or duplicate browser session' })
              res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store', Connection: 'keep-alive' })
              res.write(': connected\n\n')
              const client = { socket: new EventEmitter(), send: (event, data) => res.write(`data: ${JSON.stringify({ event, data })}\n\n`) }
              browserClients.set(id, client)
              res.once('close', () => { browserClients.delete(id); client.socket.emit('close') })
              return
            }
            if (req.method === 'POST' && url.pathname === `${BRIDGE_PATH}/browser-message` && req.headers['content-type'] === 'application/json') {
              const message = await body(req, 16 * 1024 * 1024)
              const client = browserClients.get(message.session)
              if (!client) return json(res, 404, { error: 'Browser session disconnected' })
              if (message.event === 'nadoc:viewer-register' && message.data?.id === message.session) register(message.data, client)
              else if (message.event === 'nadoc:viewer-result') result(message.data, client)
              else return json(res, 400, { error: 'Unsupported browser message' })
              return json(res, 200, { ok: true })
            }
            return json(res, 404, { error: 'Unknown browser endpoint' })
          } catch (error) { return json(res, 400, { error: error.message }) }
        }
        // Controller is local and uses an unguessable file-only credential. Browser
        // registration/results use the existing Vite socket, never this credential.
        const address = req.socket.remoteAddress
        if (!['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(address) || req.headers.origin || req.headers.authorization !== `Bearer ${token}`) return json(res, 403, { error: 'Local controller credential required' })
        try {
          if (req.method === 'GET' && url.pathname === `${BRIDGE_PATH}/sessions`) return json(res, 200, [...sessions.values()].map(value => value.info))
          if (req.method === 'GET' && url.pathname.startsWith(`${BRIDGE_PATH}/jobs/`)) {
            const job = jobs.get(url.pathname.slice(`${BRIDGE_PATH}/jobs/`.length))
            if (!job) return json(res, 404, { error: 'Unknown or expired job' })
            const { timer, ...publicJob } = job
            return json(res, 200, publicJob)
          }
          if (req.method !== 'POST' || url.pathname !== `${BRIDGE_PATH}/commands`) return json(res, 404, { error: 'Unknown endpoint' })
          let body = ''
          for await (const chunk of req) {
            body += chunk
            if (body.length > 4096) return json(res, 413, { error: 'Command too large' })
          }
          const command = validateCommand(JSON.parse(body))
          const session = sessions.get(command.session)
          if (!session) return json(res, 404, { error: 'Viewer is not connected' })
          if ([...jobs.values()].some(job => job.status === 'running')) return json(res, 409, { error: 'Another viewer command is running' })
          const currentBuild = buildInfo(server.config.root)
          if (command.action === 'capture' && (session.info.status?.build?.frontend_sha256 !== currentBuild.frontend_sha256 || !currentBuild.frontend_sha256)) return json(res, 409, { error: 'Frontend source changed since startup. Restart Vite and reload before measuring.' })
          while (jobs.size >= 32) jobs.delete(jobs.keys().next().value)
          const job = { id: randomUUID(), ...command, status: 'running', requested_at: new Date().toISOString(), verified_build: currentBuild }
          job.timer = setTimeout(() => { job.status = 'error'; job.error = 'Viewer command timed out' }, command.action === 'open' ? 240000 : (command.options.durationMs ?? 0) + 15000)
          job.timer.unref?.()
          jobs.set(job.id, job)
          session.client.send('nadoc:viewer-command', { id: job.id, action: command.action, options: command.options })
          return json(res, 202, { id: job.id })
        } catch (error) { return json(res, 400, { error: error.message }) }
      })
      server.httpServer?.once('listening', () => {
        const port = server.httpServer.address().port
        credentialsFile = bridgeCredentialsPath(server.config.root, port)
        writeFileSync(credentialsFile, JSON.stringify({ token, port, root: server.config.root, pid: process.pid }), { mode: 0o600 })
      })
      server.httpServer?.once('close', () => {
        for (const job of jobs.values()) clearTimeout(job.timer)
        if (credentialsFile) try { unlinkSync(credentialsFile) } catch { /* already cleaned */ }
      })
    }
  return {
    name: 'nadoc-local-viewer-tests', apply: 'serve',
    configureServer: configure,
    configurePreviewServer(server) { if (process.env.NADOC_VIEWER_TEST === '1') configure(server) },
  }
}
