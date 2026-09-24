#!/usr/bin/env node
/** Meeting-scoped static test host. Deliberately independent of the editor API. */
import { preparedHostBuildId } from './prepared_host_build.mjs'
import http from 'node:http'
import { readFile, readdir, writeFile, unlink } from 'node:fs/promises'
import { resolve, join, basename } from 'node:path'
import { randomBytes, timingSafeEqual, createHash } from 'node:crypto'
import { pathToFileURL } from 'node:url'
import { createPresentationState } from './prepared_room_state.mjs'
import { createRoomPresence } from './prepared_presence.mjs'
import { createEditorBroadcast } from './prepared_editor_broadcast.mjs'
import { unpackTrajectory, updateTrajectory, initialTrajectory } from './prepared_trajectory.mjs'

const same = (a, b) => typeof a === 'string' && /^[a-f0-9]{64}$/.test(a) && timingSafeEqual(Buffer.from(a), Buffer.from(b))
const mime = name => name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : name.endsWith('.html') ? 'text/html' : name.endsWith('.png') ? 'image/png' : name.endsWith('.svg') ? 'image/svg+xml' : 'application/octet-stream'

export async function createPreparedHost({ dist, packagePath, publicOrigin = '', lifetimeMs = 2 * 60 * 60 * 1000, maxGuests = 4, now = Date.now, getPublicAccess = null }) {
  if (publicOrigin && (!publicOrigin.startsWith('https://') || new URL(publicOrigin).origin !== publicOrigin)) throw new Error('Public sharing requires an exact HTTPS origin')
  if (!Number.isFinite(lifetimeMs) || lifetimeMs < 1000 || lifetimeMs > 8 * 60 * 60 * 1000) throw new Error('Lifetime must be between one second and eight hours')
  const buildId = await preparedHostBuildId(dist)
  const initial = packagePath ? await readFile(packagePath) : null
  const assets = new Map([['/viewer.html', await readFile(join(dist, 'viewer.html'))]])
  for (const name of await readdir(join(dist, 'assets'))) {
    if (/^[\w.-]+\.(js|css|png|svg|woff2?)$/.test(name)) assets.set(`/assets/${name}`, await readFile(join(dist, 'assets', name)))
  }
  const invite = randomBytes(32).toString('hex'), expiresAt = now() + lifetimeMs
  const rooms = new Map(), controlToken = randomBytes(32).toString('hex'), probeId = randomBytes(16).toString('hex')
  let publicBase = publicOrigin
  const summary = room => ({ id: room.id, title: room.title, revision: room.revision, participants: room.presentation.snapshot().participants, serverTime: now(), expiresAt, ...(room.trajectory ? { trajectory: { id: room.trajectory.id, count: room.trajectory.count, fps: room.trajectory.fps, state: room.presentation.snapshot().trajectory, serverTime: now() } } : {}), ...(room.password ? { password: room.password } : {}),
    url: `${publicBase}/viewer.html?view=${room.id}#room=${room.id}&invite=${room.invite}${room.password ? '&password=required' : ''}`,
    presenterUrl: `${publicBase}/viewer.html?view=${room.id}#room=${room.id}&invite=${room.presenterToken}&role=presenter${room.password ? '&password=required' : ''}` })
  function prepareContent(scene, replacing = null) {
    if (scene.length > 512 * 1024 * 1024 || scene.subarray(0, 8).toString() !== 'NADOCVW1') throw new Error('Choose a prepared .nadocview package (maximum 512 MiB)')
    const unpacked = unpackTrajectory(scene), others = [...rooms.values()].filter(room => room.id !== replacing)
    if (others.reduce((sum, room) => sum + room.scene.length, unpacked.scene.length) > 512 * 1024 * 1024) throw new Error('Shared views exceed the 512 MiB host capacity')
    if (others.reduce((n, room) => n + (room.trajectory?.bytes ?? 0), unpacked.trajectory?.bytes ?? 0) > 128 * 1024 * 1024) throw new Error('Host trajectory capacity reached (128 MiB). Stop an existing clip first.')
    return { ...unpacked, revision: createHash('sha256').update(unpacked.scene).digest('hex') }
  }
  function replaceShare(id, bytes, title) {
    const room = rooms.get(id)
    if (!room) throw new Error('This share has ended.')
    if (room.editorBroadcast.active) throw new Error('Turn off Broadcast to presentation before replacing the shared view.')
    const content = prepareContent(bytes, id)
    Object.assign(room, content, { title: String(title).slice(0, 200), liveFrame: null, liveLayout: null })
    room.presentation.replaceContent(room.revision, initialTrajectory(room.trajectory, now))
    return summary(room)
  }
  function createShare(bytes, title = 'Shared design', id = randomBytes(16).toString('hex')) {
    if (getPublicAccess && getPublicAccess()?.state !== 'ready') throw new Error(getPublicAccess()?.message || 'Public access checks are still running. Wait before creating an invitation.')
    if (rooms.size >= 8) throw new Error('Share capacity reached. Stop an existing share first (eight snapshots).')
    const { scene, trajectory, revision } = prepareContent(bytes)
    const room = { id, revision, title: String(title).slice(0, 200), scene, trajectory, password: publicOrigin ? randomBytes(12).toString('base64url') : '', invite: id === 'default' ? invite : randomBytes(32).toString('hex'), presenterToken: randomBytes(32).toString('hex'), sessions: new Map(), presentation: createPresentationState({ id, revision, now }) }
    if (trajectory) room.presentation.setTrajectory(initialTrajectory(trajectory, now))
    rooms.set(id, room)
    room.presence = createRoomPresence({ ...room, now })
    room.editorBroadcast = createEditorBroadcast({ room, rooms, maxGuests, now })
    return summary(room)
  }
  if (initial) createShare(initial, basename(packagePath), 'default')
  function revokeSession(room, id) {
    const session = room.sessions.get(id)
    room.sessions.delete(id)
    for (const stream of session?.streams ?? []) stream.end()
  }
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
      if (req.method === 'GET' && route === '/host/shares') return send(200, { buildId, capabilities: ['editor-broadcast-v1', 'trajectory-clip-v1', 'share-content-v1', 'job-stream-v1', 'live-timeline-v1', 'live-large-frames-v1', 'live-unlimited-frames-v1', 'guest-visualizations-v1', 'sphere-impostors-v1', 'view-tools-v1', 'annotations-v1', 'selection-ping-v1', 'visualization-labels-v1', 'multi-overlay-v1', 'hull-cutouts-v1'], expiresAt, publicAccess: getPublicAccess?.(), shares: [...rooms.values()].map(summary) })
      const content = route.match(/^\/host\/shares\/([a-f0-9]{32})\/content$/)
      if (req.method === 'POST' && content) {
        if (!rooms.has(content[1])) return send(410, { error: 'This share has ended.' })
        try {
          const chunks = []; let size = 0
          for await (const chunk of req) { size += chunk.length; if (size > 512 * 1024 * 1024) return send(413, { error: 'Package too large' }); chunks.push(chunk) }
          return send(200, replaceShare(content[1], Buffer.concat(chunks), decodeURIComponent(req.headers['x-nadoc-title'] ?? 'Shared design')))
        } catch (error) { return send(409, { error: error.message }) }
      }
      const timeline = route.match(/^\/host\/shares\/([a-f0-9]{32})\/trajectory$/)
      if (['GET', 'POST'].includes(req.method) && timeline) {
        const room = rooms.get(timeline[1]); if (!room) return send(410, { error: 'This share has ended.' })
        if (req.method === 'GET') return send(200, room.presentation.snapshot())
        try {
          const chunks = []; let size = 0
          for await (const chunk of req) { size += chunk.length; if (size > 2048) return send(413, { error: 'Command too large' }); chunks.push(chunk) }
          return send(200, updateTrajectory(room, JSON.parse(Buffer.concat(chunks)), now))
        } catch (error) { return send(400, { error: error.message }) }
      }
      const broadcast = route.match(/^\/host\/shares\/([a-f0-9]{32})\/broadcast\/(start|camera|scene|frame|hold|pause|heartbeat|progress)$/)
      if (req.method === 'POST' && broadcast) {
        const room = rooms.get(broadcast[1]); if (!room) return send(410, { error: 'This share has ended.' })
        try {
          const action = broadcast[2], limit = action === 'scene' ? 512 * 1024 * 1024 : action === 'frame' ? Infinity : 4096
          const chunks = []; let size = 0
          for await (const chunk of req) { size += chunk.length; if (size > limit) return send(413, { error: 'Broadcast update too large' }); chunks.push(chunk) }
          const body = Buffer.concat(chunks)
          return send(200, action === 'start' ? room.editorBroadcast.start(body.length ? JSON.parse(body) : {}) : room.editorBroadcast.apply(action, req.headers['x-nadoc-broadcast'], body))
        } catch (error) { return send(409, { error: error.message }) }
      }
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
    if (req.method === 'GET' && route === '/__nadoc_public_health') return send(200, { service: 'nadoc-prepared-viewer', probeId })
    if (publicOrigin && management) return send(404, { error: 'Not found' })
    const match = route?.match(/^\/meeting\/([a-f0-9]{32}|default)\/(join|scene|status|events|camera|share-view|health|pause|leave|trajectory|frame|live-frame)$/)
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
        if (role === 'presenter' && room.editorBroadcast.active) return send(409, { error: 'The NADOC editor is presenting. Turn off Broadcast to presentation before using this presenter page.' })
        if (!same(value.token, role === 'presenter' ? room.presenterToken : room.invite)) return send(403, { error: 'Invalid or expired invite.' })
        const previous = req.headers.cookie?.match(cookiePattern)?.[1]
        // Keep presenter credentials and their occupied slot until the meeting
        // ends. Leaving the viewer does not revoke the meeting or its guests.
        for (const r of rooms.values()) for (const [key, s] of r.sessions) if (s.role !== 'presenter' && now() - s.seenAt > 120000) revokeSession(r, key)
        if (value.resume === true) {
          const existing = sessions.get(previous)
          if (!existing || existing.role !== role) return send(401, { error: 'Please sign in to this view.' })
          existing.away = false; existing.seenAt = now(); existing.generation++
          return send(200, { name: existing.name, participantId: room.presence.identify(existing), role, revision: room.revision, expiresAt })
        }
        // Generated passwords contain 96 bits of entropy; compare fixed-size hashes.
        if (room.password && (typeof value.password !== 'string' || !timingSafeEqual(createHash('sha256').update(value.password).digest(), createHash('sha256').update(room.password).digest()))) return send(403, { error: 'Incorrect meeting password.' })
        const name = typeof value.name === 'string' ? value.name.trim() : ''
        if (!name || name.length > 40 || /[\x00-\x1f\x7f]/.test(name)) return send(400, { error: 'Enter a display name of 1–40 characters.' })
        // A separately authenticated presenter can reclaim an absent presenter's
        // place, without changing the invitation or any guest's session.
        if (role === 'presenter') for (const [key, s] of sessions) {
          if (key !== previous && s.role === 'presenter' && (s.away || now() - s.seenAt > 120000)) revokeSession(room, key)
        }
        if (role === 'presenter' && [...sessions].some(([key, session]) => session.role === 'presenter' && key !== previous)) return send(409, { error: 'A presenter is already connected to this view.' })
        if (!sessions.has(previous) && [...rooms.values()].reduce((n, r) => n + r.sessions.size + Number(r.editorBroadcast.active && ![...r.sessions.values()].some(s => s.role === 'presenter')), 0) >= maxGuests) return send(409, { error: 'This presentation is full (four participants including the presenter).' })
        // Reauthentication (especially a role change) must invalidate the old cookie
        // and its event streams. Preserve display identity only within the same role.
        const previousSession = sessions.get(previous)
        const identity = previousSession?.role === role ? previousSession : null
        const id = randomBytes(32).toString('hex')
        revokeSession(room, previous)
        const joined = { participantId: identity?.participantId, color: identity?.color, name, role, seenAt: now(), away: false, generation: 0, streams: new Set() }
        sessions.set(id, joined)
        return send(200, { name, participantId: room.presence.identify(joined), role, revision: room.revision, expiresAt }, 'application/json', { 'Set-Cookie': `${cookieName}=${id}; HttpOnly; SameSite=Strict; Path=/; Max-Age=${Math.max(1, Math.floor((expiresAt - now()) / 1000))}${publicOrigin ? '; Secure' : ''}` })
      } catch { return send(400, { error: 'Invalid join request.' }) }
    }
    const sessionId = req.headers.cookie?.match(cookiePattern)?.[1], session = sessions?.get(sessionId)
    if (session) session.seenAt = now()
    if (req.method === 'POST' && ['/meeting/share-view', '/meeting/health'].includes(route)) {
      if (req.headers.origin !== (publicOrigin || `http://${req.headers.host}`) || session?.role !== 'guest') return send(403, { error: 'Guest access required' })
      try {
        const chunks = []; let size = 0
        for await (const chunk of req) { size += chunk.length; if (size > 2048) return send(413, { error: 'Camera message too large' }); chunks.push(chunk) }
        if (sessions.get(sessionId) !== session) return send(403, { error: 'Sign in again before sharing' })
        return send(200, room.presence[route === '/meeting/health' ? 'health' : 'share'](session, JSON.parse(Buffer.concat(chunks))))
      } catch (error) { return send(409, { error: error.message }) }
    }
    if (req.method === 'POST' && ['/meeting/camera', '/meeting/pause', '/meeting/leave', '/meeting/trajectory'].includes(route)) {
      if (room.editorBroadcast.active) return send(403, { error: 'The editor is presenting this view.' })
      if (req.headers.origin !== (publicOrigin || `http://${req.headers.host}`) || session?.role !== 'presenter') return send(403, { error: 'Presenter access required' })
      if (route === '/meeting/leave') { session.away = true; session.generation++; room.presentation.leavePresenter(); return send(200, { ok: true }) }
      if (route === '/meeting/pause') { room.presentation.pause(); return send(200, { ok: true }) }
      const generation = session.generation
      try {
        const chunks = []; let size = 0
        for await (const chunk of req) { size += chunk.length; if (size > 2048) return send(413, { error: 'Camera message too large' }); chunks.push(chunk) }
        if (session.away || session.generation !== generation || sessions.get(sessionId) !== session) return send(403, { error: 'Return to the presentation before sharing a perspective.' })
        return send(200, route === '/meeting/trajectory' ? updateTrajectory(room, JSON.parse(Buffer.concat(chunks)), now) : room.presentation.publish(JSON.parse(Buffer.concat(chunks))))
      } catch (error) { return send(error.message.startsWith('Too many') ? 429 : 400, { error: error.message }) }
    }
    if (req.method !== 'GET') return send(405, { error: 'Read-only viewer' }, 'application/json', { Allow: 'GET, POST' })
    if (route === '/meeting/live-frame') {
      if (!session) return send(401, { error: 'Join with the invite link first.' })
      const query = new URL(req.url, 'http://localhost').searchParams, frame = room.liveFrame
      if (!frame || query.get('revision') !== frame.revision) return send(409, { error: 'A newer visualization is available.' })
      // Capture the latest frame atomically. A slow guest must not chase an already
      // obsolete sequence forever when its round-trip exceeds the playback interval.
      if ((session.frameRequests ?? 0) >= 2) return send(429, { error: 'Wait for the pending frame' })
      session.frameRequests = (session.frameRequests ?? 0) + 1
      res.once('close', () => { session.frameRequests-- })
      return send(200, frame.buffer, 'application/octet-stream', { 'Content-Length': frame.bytes, 'X-NADOC-Sequence': frame.sequence, 'X-NADOC-Timeline': JSON.stringify(frame.timeline ?? null), 'X-NADOC-SHA256': frame.sha256 })
    }
    if (route === '/meeting/frame') {
      if (!session) return send(401, { error: 'Join with the invite link first.' })
      const query = new URL(req.url, 'http://localhost').searchParams, index = Number(query.get('index'))
      if (!room.trajectory || query.get('clip') !== room.trajectory.id || !query.has('index') || !Number.isSafeInteger(index) || index < 0 || index >= room.trajectory.frames.length) return send(404, { error: 'Unknown trajectory frame' })
      if ((session.frameRequests ?? 0) >= 2) return send(429, { error: 'Wait for the pending frame' })
      session.frameRequests = (session.frameRequests ?? 0) + 1
      res.once('close', () => { session.frameRequests-- })
      const frame = room.trajectory.frames[index]
      return send(200, frame, 'application/octet-stream', { 'Content-Length': frame.length })
    }
    if (route === '/meeting/scene' || route === '/meeting/status' || route === '/meeting/events') {
      if (!session) return send(401, { error: 'Join with the invite link first.' })
      if (route === '/meeting/status') return send(200, { name: session.name, role: session.role, revision: room.revision, expiresAt, presentation: room.presentation.snapshot() })
      if (route === '/meeting/events') {
        if (session.away) return send(409, { error: 'Return to the presentation to reconnect.' })
        session.streams ??= new Set()
        if (session.streams.size >= 2) return send(429, { error: 'Close another viewer tab before connecting again.' }, 'application/json', { 'Retry-After': '10' })
        res.writeHead(200, { ...headers, 'Content-Type': 'text/event-stream', Connection: 'keep-alive', 'X-Accel-Buffering': 'no' })
        if (!room.presentation.subscribe(res, { presenter: session.role === 'presenter' })) return
        session.streams.add(res)
        res.once('close', () => session.streams.delete(res))
        room.presence.connect(session, res)
        const heartbeat = setInterval(() => {
          if (sessions.get(sessionId) !== session) { res.end(); return }
          session.seenAt = now(); if (!res.write(': heartbeat\n\n')) res.destroy()
        }, 10000)
        res.on('close', () => { clearInterval(heartbeat) })
        return
      }
      const expected = new URL(req.url, 'http://localhost').searchParams.get('revision')
      if (expected && expected !== room.revision) return send(409, { error: 'A newer visualization is available.' })
      if ((session.sceneRequests ?? 0) >= 2) return send(429, { error: 'Wait for the pending visualization download' }, 'application/json', { 'Retry-After': '2' })
      session.sceneRequests = (session.sceneRequests ?? 0) + 1
      res.once('close', () => { session.sceneRequests-- })
      return send(200, room.scene, 'application/octet-stream', { 'Content-Length': room.scene.length, 'X-NADOC-Revision': room.revision })
    }
    const key = route === '/' ? '/viewer.html' : route
    if (!assets.has(key)) return send(404, { error: 'Not found' })
    return send(200, assets.get(key), mime(key))
  }
  const server = http.createServer(handler(!publicOrigin))
  const controlServer = publicOrigin ? http.createServer(handler(true)) : null
  server.requestTimeout = 15000; server.headersTimeout = 10000
  if (controlServer) { controlServer.requestTimeout = 15000; controlServer.headersTimeout = 10000 }
  const leases = setInterval(() => { if (now() >= expiresAt) { stop(); return }; for (const room of rooms.values()) { room.editorBroadcast.expire(); room.presence.expireHealth() } }, 1000); leases.unref()
  const stop = () => { closed = true; clearInterval(leases); for (const room of rooms.values()) room.presentation.close(); rooms.clear(); for (const listener of [server, controlServer]) { listener?.close(); if (listener) setTimeout(() => listener.closeAllConnections(), 250).unref() } }
  return { probeId, server, controlServer, invite, expiresAt, stop, controlToken, createShare, setPublicBase: value => { if (publicOrigin && value !== publicOrigin) throw new Error('Public origin is fixed'); publicBase = value } }
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
  console.log(`Prepared host${flags['--package'] ? ': ' + basename(flags['--package']) : ''}\n${flags['--package'] ? `Invite: http://${host}:${port}/viewer.html#invite=${app.invite}` : 'Use NADOC File → Sharing to publish the current part.'}\nExpires: ${new Date(app.expiresAt).toISOString()}\nCtrl-C stops this host immediately. Anyone with this link on your trusted network can join (four browsers maximum).`)
  app.server.once('close', () => clearTimeout(timer))
  const timer = setTimeout(() => { console.log('Test session expired.'); app.stop() }, app.expiresAt - Date.now())
  const stop = () => { clearTimeout(timer); app.stop() }
  process.once('SIGINT', stop); process.once('SIGTERM', stop)
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) main().catch(error => { console.error(error.message); process.exitCode = 1 })
