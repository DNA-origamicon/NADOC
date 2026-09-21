#!/usr/bin/env node
/** Meeting-scoped static test host. Deliberately independent of the editor API. */
import http from 'node:http'
import { readFile, readdir, writeFile, unlink } from 'node:fs/promises'
import { resolve, join, basename } from 'node:path'
import { randomBytes, timingSafeEqual, createHash } from 'node:crypto'
import { pathToFileURL } from 'node:url'
import { createPresentationState } from './prepared_room_state.mjs'

const same = (a, b) => typeof a === 'string' && /^[a-f0-9]{64}$/.test(a) && timingSafeEqual(Buffer.from(a), Buffer.from(b))
const mime = name => name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : name.endsWith('.html') ? 'text/html' : name.endsWith('.png') ? 'image/png' : name.endsWith('.svg') ? 'image/svg+xml' : 'application/octet-stream'

export async function createPreparedHost({ dist, packagePath, publicOrigin = '', lifetimeMs = 2 * 60 * 60 * 1000, maxGuests = 4, now = Date.now }) {
  if (publicOrigin && (!publicOrigin.startsWith('https://') || new URL(publicOrigin).origin !== publicOrigin)) throw new Error('Public sharing requires an exact HTTPS origin')
  if (!Number.isFinite(lifetimeMs) || lifetimeMs < 1000 || lifetimeMs > 8 * 60 * 60 * 1000) throw new Error('Lifetime must be between one second and eight hours')
  const initial = packagePath ? await readFile(packagePath) : null
  const assets = new Map([['/viewer.html', await readFile(join(dist, 'viewer.html'))]])
  for (const name of await readdir(join(dist, 'assets'))) {
    if (/^[\w.-]+\.(js|css|png|svg|woff2?)$/.test(name)) assets.set(`/assets/${name}`, await readFile(join(dist, 'assets', name)))
  }
  const invite = randomBytes(32).toString('hex'), expiresAt = now() + lifetimeMs
  const rooms = new Map(), controlToken = randomBytes(32).toString('hex')
  let publicBase = publicOrigin
  const summary = room => ({ id: room.id, title: room.title, revision: room.revision, expiresAt, ...(room.password ? { password: room.password } : {}),
    url: `${publicBase}/viewer.html?view=${room.id}#room=${room.id}&invite=${room.invite}${room.password ? '&password=required' : ''}`,
    presenterUrl: `${publicBase}/viewer.html?view=${room.id}#room=${room.id}&invite=${room.presenterToken}&role=presenter${room.password ? '&password=required' : ''}` })
  function createShare(scene, title = 'Shared design', id = randomBytes(16).toString('hex')) {
    if (scene.length > 512 * 1024 * 1024 || scene.subarray(0, 8).toString() !== 'NADOCVW1') throw new Error('Choose a prepared .nadocview package (maximum 512 MiB)')
    if (rooms.size >= 8 || [...rooms.values()].reduce((sum, room) => sum + room.scene.length, scene.length) > 512 * 1024 * 1024) throw new Error('Share capacity reached. Stop an existing share first (eight snapshots / 512 MiB).')
    const revision = createHash('sha256').update(scene).digest('hex')
    const room = { id, revision, title: String(title).slice(0, 200), scene, password: publicOrigin ? randomBytes(12).toString('base64url') : '', invite: id === 'default' ? invite : randomBytes(32).toString('hex'), presenterToken: randomBytes(32).toString('hex'), sessions: new Map(), presentation: createPresentationState({ id, revision, now }) }
    rooms.set(id, room)
    return summary(room)
  }
  if (initial) createShare(initial, basename(packagePath), 'default')
  let closed = false
  let joinWindow = now(), joinAttempts = 0
  const handler = management => async (req, res) => {
    const headers = { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
      'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'" }
    const send = (code, body, type = 'application/json', extra = {}) => { res.writeHead(code, { ...headers, 'Content-Type': type, ...extra }); res.end(type === 'application/json' ? JSON.stringify(body) : body) }
    if (closed || now() >= expiresAt) return send(410, { error: 'This test session has ended.' })
    let route = req.url?.split('?')[0]
    if (route?.startsWith('/host/')) {
      if (!management) return send(404, { error: 'Not found' })
      if (req.headers.origin || !same(req.headers.authorization?.replace(/^Bearer /, ''), controlToken)) return send(403, { error: 'Local host credential required' })
      if (req.method === 'GET' && route === '/host/shares') return send(200, { expiresAt, shares: [...rooms.values()].map(summary) })
      if (req.method === 'DELETE' && /^\/host\/shares\/[a-f0-9]{32}$/.test(route)) {
        const id = route.split('/').pop(); rooms.get(id)?.presentation.close(); rooms.delete(id); return send(200, { ok: true })
      }
      if (req.method === 'POST' && route === '/host/stop') { send(200, { ok: true }); setTimeout(stop, 100); return }
      if (req.method === 'POST' && route === '/host/shares') {
        try {
          const chunks = []; let size = 0
          for await (const chunk of req) { size += chunk.length; if (size > 512 * 1024 * 1024) return send(413, { error: 'Package too large' }); chunks.push(chunk) }
          return send(201, createShare(Buffer.concat(chunks), decodeURIComponent(req.headers['x-nadoc-title'] ?? 'Shared design')))
        } catch (error) { return send(400, { error: error.message }) }
      }
      return send(404, { error: 'Unknown host action' })
    }
    if (publicOrigin && management) return send(404, { error: 'Not found' })
    const match = route?.match(/^\/meeting\/([a-f0-9]{32}|default)\/(join|scene|status|events|camera|pause)$/)
    const room = rooms.get(match ? match[1] : 'default')
    if (match) route = `/meeting/${match[2]}`
    if (route?.startsWith('/meeting/') && !room) return send(410, { error: 'This share has ended.' })
    const sessions = room?.sessions
    const cookieName = room?.id === 'default' ? 'nadoc_view' : `nadoc_view_${room?.id}`
    const cookiePattern = new RegExp(`(?:^|;\\s*)${cookieName}=([a-f0-9]{64})(?:;|$)`)
    if (req.method === 'POST' && route === '/meeting/join') {
      if (req.headers.origin !== (publicOrigin || `http://${req.headers.host}`)) return send(403, { error: 'Open the invite in this browser.' })
      // Bound unauthenticated work without trusting proxy-supplied client IPs.
      if (now() - joinWindow >= 60000) { joinWindow = now(); joinAttempts = 0 }
      if (++joinAttempts > 60) return send(429, { error: 'Too many join attempts. Please wait one minute.' }, 'application/json', { 'Retry-After': '60' })
      try {
        let body = '', bytes = 0
        for await (const chunk of req) { bytes += chunk.length; if (bytes > 2048) { send(413, { error: 'Request too large' }); return } body += chunk.toString() }
        const value = JSON.parse(body)
        const role = value.role === 'presenter' ? 'presenter' : 'guest'
        if (!same(value.token, role === 'presenter' ? room.presenterToken : room.invite)) return send(403, { error: 'Invalid or expired invite.' })
        // Generated passwords contain 96 bits of entropy; compare fixed-size hashes.
        if (room.password && (typeof value.password !== 'string' || !timingSafeEqual(createHash('sha256').update(value.password).digest(), createHash('sha256').update(room.password).digest()))) return send(403, { error: 'Incorrect meeting password.' })
        const name = typeof value.name === 'string' ? value.name.trim() : ''
        if (!name || name.length > 40 || /[\x00-\x1f\x7f]/.test(name)) return send(400, { error: 'Enter a display name of 1–40 characters.' })
        const previous = req.headers.cookie?.match(cookiePattern)?.[1]
        // Four participants across the host, including the presenter. Closed tabs
        // release their leases after two minutes without an authenticated heartbeat.
        for (const r of rooms.values()) for (const [key, session] of r.sessions) if (now() - session.seenAt > 120000) r.sessions.delete(key)
        if (role === 'presenter' && [...sessions].some(([key, session]) => session.role === 'presenter' && key !== previous)) return send(409, { error: 'A presenter is already connected to this view.' })
        if (!sessions.has(previous) && [...rooms.values()].reduce((n, r) => n + r.sessions.size, 0) >= maxGuests) return send(409, { error: 'This presentation is full (four participants including the presenter).' })
        const id = sessions.has(previous) ? previous : randomBytes(32).toString('hex')
        sessions.set(id, { name, role, seenAt: now() })
        return send(200, { name, role, revision: room.revision, expiresAt }, 'application/json', { 'Set-Cookie': `${cookieName}=${id}; HttpOnly; SameSite=Strict; Path=/; Max-Age=${Math.max(1, Math.floor((expiresAt - now()) / 1000))}${publicOrigin ? '; Secure' : ''}` })
      } catch { return send(400, { error: 'Invalid join request.' }) }
    }
    const sessionId = req.headers.cookie?.match(cookiePattern)?.[1], session = sessions?.get(sessionId)
    if (session) session.seenAt = now()
    if (req.method === 'POST' && (route === '/meeting/camera' || route === '/meeting/pause')) {
      if (req.headers.origin !== (publicOrigin || `http://${req.headers.host}`) || session?.role !== 'presenter') return send(403, { error: 'Presenter access required' })
      if (route === '/meeting/pause') { room.presentation.pause(); return send(200, { ok: true }) }
      try {
        const chunks = []; let size = 0
        for await (const chunk of req) { size += chunk.length; if (size > 2048) return send(413, { error: 'Camera message too large' }); chunks.push(chunk) }
        return send(200, room.presentation.publish(JSON.parse(Buffer.concat(chunks))))
      } catch (error) { return send(error.message.startsWith('Too many') ? 429 : 400, { error: error.message }) }
    }
    if (req.method !== 'GET') return send(405, { error: 'Read-only viewer' }, 'application/json', { Allow: 'GET, POST' })
    if (route === '/meeting/scene' || route === '/meeting/status' || route === '/meeting/events') {
      if (!session) return send(401, { error: 'Join with the invite link first.' })
      if (route === '/meeting/status') return send(200, { name: session.name, role: session.role, revision: room.revision, expiresAt, presentation: room.presentation.snapshot() })
      if (route === '/meeting/events') {
        res.writeHead(200, { ...headers, 'Content-Type': 'text/event-stream', Connection: 'keep-alive', 'X-Accel-Buffering': 'no' })
        room.presentation.subscribe(res, { presenter: session.role === 'presenter' })
        const heartbeat = setInterval(() => {
          if (sessions.get(sessionId) !== session) { res.end(); return }
          session.seenAt = now(); if (!res.write(': heartbeat\n\n')) res.destroy()
        }, 10000)
        res.on('close', () => { clearInterval(heartbeat) })
        return
      }
      return send(200, room.scene, 'application/octet-stream', { 'Content-Length': room.scene.length })
    }
    const key = route === '/' ? '/viewer.html' : route
    if (!assets.has(key)) return send(404, { error: 'Not found' })
    return send(200, assets.get(key), mime(key))
  }
  const server = http.createServer(handler(!publicOrigin))
  const controlServer = publicOrigin ? http.createServer(handler(true)) : null
  server.requestTimeout = 15000; server.headersTimeout = 10000
  if (controlServer) { controlServer.requestTimeout = 15000; controlServer.headersTimeout = 10000 }
  const stop = () => { closed = true; for (const room of rooms.values()) room.presentation.close(); rooms.clear(); for (const listener of [server, controlServer]) { listener?.close(); listener?.closeAllConnections() } }
  return { server, controlServer, invite, expiresAt, stop, controlToken, createShare, setPublicBase: value => { if (publicOrigin && value !== publicOrigin) throw new Error('Public origin is fixed'); publicBase = value } }
}

async function main() {
  const flags = Object.fromEntries(process.argv.slice(2).reduce((pairs, value, i, args) => i % 2 ? pairs : [...pairs, [value, args[i + 1]]], []))
  if (!flags['--package'] && !flags['--control-file']) throw new Error('Usage: node scripts/prepared_view_host.mjs --package FILE --dist frontend/dist --bind LAN_IP --port 5182 --minutes 120')
  const host = flags['--bind'] ?? '127.0.0.1', port = Number(flags['--port'] ?? 5182)
  if (!/^(?:\d{1,3}\.){3}\d{1,3}$/.test(host) || !Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Choose an IPv4 interface and port 1024–65535')
  const app = await createPreparedHost({ dist: resolve(flags['--dist'] ?? 'frontend/dist'), packagePath: flags['--package'] ? resolve(flags['--package']) : null, lifetimeMs: Number(flags['--minutes'] ?? 120) * 60000 })
  await new Promise((ok, fail) => { app.server.once('error', fail); app.server.listen(port, host, ok) })
  app.setPublicBase(`http://${host}:${port}`)
  const controlFile = flags['--control-file']
  if (controlFile) {
    await writeFile(controlFile, JSON.stringify({ url: `http://${host}:${port}`, token: app.controlToken, expiresAt: app.expiresAt }), { mode: 0o600 })
    app.server.once('close', () => { unlink(controlFile).catch(() => {}) })
  }
  console.log(`Prepared host${flags['--package'] ? ': ' + basename(flags['--package']) : ''}\n${flags['--package'] ? `Invite: http://${host}:${port}/viewer.html#invite=${app.invite}` : 'Use NADOC Help → Share link to publish the current part.'}\nExpires: ${new Date(app.expiresAt).toISOString()}\nCtrl-C stops this host immediately. Anyone with this link on your trusted network can join (four browsers maximum).`)
  app.server.once('close', () => clearTimeout(timer))
  const timer = setTimeout(() => { console.log('Test session expired.'); app.stop() }, app.expiresAt - Date.now())
  const stop = () => { clearTimeout(timer); app.stop() }
  process.once('SIGINT', stop); process.once('SIGTERM', stop)
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) main().catch(error => { console.error(error.message); process.exitCode = 1 })
